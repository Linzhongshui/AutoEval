"""Recovery using real PostgreSQL, terminated Temporal workflows and Docker jobs."""

import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import select
from temporalio.client import Client

from autoeval.api import create_app
from autoeval.config import get_settings
from autoeval.docker_executor import DockerExecutor
from autoeval.models import Outbox
from autoeval.reconciler import reconcile_diagnostic
from autoeval.resources import ResourceBinding
from autoeval.runs import ExecutionLease
from autoeval.workflows import DockerDiagnosticWorkflow

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_DOCKER_TEST"), reason="Live services required"
)


async def test_recover_closed_workflow_without_restarting_job():
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
    ):
        async with app.state.sessions() as session:
            binding = await session.scalar(select(ResourceBinding).limit(1))
            assert binding is not None
        response = await api.post(
            "/api/autoeval/v1/diagnostics/runs",
            json={
                "resource_binding_id": str(binding.id),
                "kind": "framework_smoke",
                "duration_seconds": 0,
            },
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )
        assert response.status_code == 202
        run_id = uuid.UUID(response.json()["data"]["run_id"])
        # Keep this fault-injection run away from the development dispatcher.
        async with app.state.sessions() as session, session.begin():
            intent = await session.scalar(
                select(Outbox).where(Outbox.run_id == run_id).with_for_update()
            )
            intent.state = "delivered"
        handle = await client.start_workflow(
            DockerDiagnosticWorkflow.run,
            str(run_id),
            id=f"demo/run/{run_id}",
            task_queue="fault-injection-" + uuid.uuid4().hex,
        )
        assert (
            await reconcile_diagnostic(app.state.sessions, client, settings, run_id)
            == "workflow_active"
        )
        await handle.terminate("Integration fault injection before state projection")
        # No external job was submitted: never infer cancellation or release ownership.
        assert (
            await reconcile_diagnostic(app.state.sessions, client, settings, run_id) == "unresolved"
        )
        assert (
            await reconcile_diagnostic(app.state.sessions, client, settings, run_id) == "unresolved"
        )
        detail = (await api.get(f"/api/autoeval/v1/diagnostics/runs/{run_id}")).json()["data"]
        assert detail["execution_unresolved"] is True
        assert detail["ownership_held"] is True
        assert [event["type"] for event in detail["events"]].count("execution_unresolved") == 1
        audits = (
            await api.get("/api/autoeval/v1/audit-events", params={"run_id": str(run_id)})
        ).json()["data"]
        assert [event["action"] for event in audits].count("recovery.unresolved") == 1
        async with app.state.sessions() as session:
            assert await session.scalar(
                select(ExecutionLease).where(ExecutionLease.run_id == run_id)
            )
        adapter = DockerExecutor(settings.docker_executable, binding.container_id, binding.image_id)
        job = await adapter.submit({"kind": "framework_smoke", "duration_seconds": 0}, str(run_id))
        for _ in range(30):
            if (await adapter.status(job)).state == "succeeded":
                break
            await asyncio.sleep(0.2)
        assert (
            await reconcile_diagnostic(app.state.sessions, client, settings, run_id) == "completed"
        )
        assert (
            await reconcile_diagnostic(app.state.sessions, client, settings, run_id) == "terminal"
        )
        data = (await api.get(f"/api/autoeval/v1/diagnostics/runs/{run_id}")).json()["data"]
        assert data["result"]["reconciled"] is True
        assert data["result"]["result"]["model_called"] is False
        async with app.state.sessions() as session:
            assert (
                await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == run_id))
                is None
            )
