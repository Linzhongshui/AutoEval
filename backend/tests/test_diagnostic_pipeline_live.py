"""Actual HTTP/SQL/outbox/Temporal/Docker integration; no model inference."""

import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import select
from temporalio.client import Client
from temporalio.worker import Worker

from autoeval.api import create_app
from autoeval.config import get_settings
from autoeval.dispatcher import deliver_once
from autoeval.resources import ResourceBinding
from autoeval.run_activities import execute_docker_diagnostic
from autoeval.workflows import DockerDiagnosticWorkflow

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_DOCKER_TEST"), reason="Live Docker and infrastructure required"
)


async def test_diagnostic_submit_deduplicate_execute_and_cancel():
    settings = get_settings()
    app = create_app()
    client = await Client.connect(settings.temporal_address)
    async with (
        app.router.lifespan_context(app),
        Worker(client, task_queue="demo.workflow.v1", workflows=[DockerDiagnosticWorkflow]),
        Worker(client, task_queue="demo.io.v1", activities=[execute_docker_diagnostic]),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
    ):
        async with app.state.sessions() as session:
            binding = await session.scalar(select(ResourceBinding).limit(1))
            assert binding is not None, "Register the local executor first"
            binding_id = str(binding.id)
        for cancel in (False, True):
            body = {
                "resource_binding_id": binding_id,
                "kind": "framework_smoke",
                "duration_seconds": 15 if cancel else 0,
            }
            path = "/api/autoeval/v1/diagnostics/runs"
            headers = {"Idempotency-Key": "test-" + uuid.uuid4().hex}
            response = await api.post(path, json=body, headers=headers)
            assert response.status_code == 202, response.text
            run_id = response.json()["data"]["run_id"]
            duplicate = await api.post(path, json=body, headers=headers)
            assert duplicate.json()["data"]["run_id"] == run_id
            conflict = await api.post(path, json={**body, "duration_seconds": 1}, headers=headers)
            assert conflict.status_code == 409
            for _ in range(20):
                if not await deliver_once(app.state.sessions, client):
                    break
            cancellation_sent = False
            for _ in range(120):
                data = (await api.get(f"{path}/{run_id}")).json()["data"]
                if cancel and data["state"] == "running" and not cancellation_sent:
                    assert (await api.post(f"{path}/{run_id}/cancel")).status_code == 202
                    cancellation_sent = True
                if data["state"] in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.5)
            assert data["state"] == ("cancelled" if cancel else "completed"), data
            assert data["result"]["diagnostic_only"] is True
            assert data["gate_status"] == "not_applicable"
            events = data["events"]
            assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
