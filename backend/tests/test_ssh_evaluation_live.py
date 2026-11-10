"""Real SQL/S3/Temporal/SSH/native scoring; the model boundary is explicitly simulated."""

import asyncio
import hashlib
import json
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from temporalio.client import Client
from temporalio.worker import Worker

from autoeval import evaluation_activity
from autoeval.api import create_app
from autoeval.case_history import AttemptInput, CaseExecutionRecord, begin_attempt
from autoeval.config import get_settings
from autoeval.configuration import TestConfigItem as ConfigItem
from autoeval.configuration import TestConfigVersion as ConfigVersion
from autoeval.datasets import DatasetManifest, read_manifest
from autoeval.dispatcher import deliver_once
from autoeval.execution_transport import ssh_transport
from autoeval.models import Outbox, RunSnapshot
from autoeval.profiles import ConfigDatasetBinding, EvaluationProfile
from autoeval.reconciler import reconcile_gpqa
from autoeval.run_activities import transition
from autoeval.ssh_native import SSHNativeTransport
from autoeval.ssh_resources import SSHResourceBinding
from autoeval.targets import TargetBinding
from autoeval.workflows import GpqaExplorationWorkflow

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_SSH_NATIVE_PIPELINE_TEST"),
    reason="Prepared local SSH native environment required",
)


@pytest.fixture
async def harness(monkeypatch):
    settings = get_settings().model_copy(
        update={
            "evaluation_origin": "simulation",
            "analysis_target_id": None,
            "analysis_resource_id": None,
            "gpqa_workflow_queue": "ssh-test-wf-" + uuid.uuid4().hex,
            "gpqa_activity_queue": "ssh-test-io-" + uuid.uuid4().hex,
        }
    )
    monkeypatch.setattr(evaluation_activity, "get_settings", lambda: settings)

    def forbid_docker(*args, **kwargs):
        raise AssertionError("Customer SSH execution must not call Docker control APIs")

    monkeypatch.setattr(evaluation_activity, "inspect_executor", forbid_docker)
    monkeypatch.setattr(evaluation_activity, "invoke", forbid_docker)
    app = create_app(settings)
    client = await Client.connect(settings.temporal_address)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
        Worker(
            client, task_queue=settings.gpqa_workflow_queue, workflows=[GpqaExplorationWorkflow]
        ),
        Worker(
            client,
            task_queue=settings.gpqa_activity_queue,
            activities=[evaluation_activity.execute_gpqa_exploration],
        ),
    ):
        lock = json.loads(settings.aisbench_lock_path.read_text())
        async with app.state.sessions() as session:
            config = await session.scalar(
                select(ConfigVersion)
                .join(ConfigItem, ConfigItem.config_version_id == ConfigVersion.id)
                .join(ConfigDatasetBinding, ConfigDatasetBinding.config_item_id == ConfigItem.id)
                .join(EvaluationProfile, EvaluationProfile.id == ConfigDatasetBinding.profile_id)
                .join(DatasetManifest, DatasetManifest.id == ConfigDatasetBinding.manifest_id)
                .where(
                    DatasetManifest.sample_count == 1,
                    DatasetManifest.scope == "lite",
                    EvaluationProfile.contract["revision"].astext == lock["revision"],
                )
                .order_by(ConfigVersion.created_at.desc())
                .limit(1)
            )
            resource = await session.scalar(
                select(SSHResourceBinding)
                .where(
                    SSHResourceBinding.host == "127.0.0.1",
                    SSHResourceBinding.port == 2222,
                    SSHResourceBinding.native_tool_root == "/opt/autoeval-tools/aisbench",
                )
                .limit(1)
            )
            target = await session.scalar(
                select(TargetBinding)
                .where(TargetBinding.remote_model == "deepseek-flash")
                .order_by(TargetBinding.created_at)
                .limit(1)
            )
            assert config and resource and target, (
                "Prepare GPQA Lite1 configuration and local SSH tools first"
            )
        body = {
            "config_version_id": str(config.id),
            "resource_id": str(resource.id),
            "target_id": str(target.id),
            "resource_kind": "customer_ssh",
            "run_mode": "exploration",
            "max_model_requests": 1,
        }
        yield app, api, client, settings, body


async def wait_terminal(api, run_id):
    for _ in range(150):
        body = (await api.get(f"/api/autoeval/v1/runs/{run_id}")).json()["data"]
        if body["state"] in {"completed", "failed", "cancelled"}:
            return body
        await asyncio.sleep(0.2)
    raise AssertionError("SSH run did not finish")


async def test_ssh_submission_snapshot_report_and_cancel(harness, monkeypatch):
    app, api, client, _settings, body = harness
    calls = []

    async def simulated_model(transport, payload, key):
        calls.append(key)
        prompt = await asyncio.to_thread(
            transport.invoke_local, {"operation": "prompt_gpqa_0shot", "sample": payload["sample"]}
        )
        return {
            "tool_revision": prompt["tool_revision"],
            "prompt": prompt["prompt"],
            "state": "succeeded",
            "response": payload["sample"]["answer"],
            "finish_reason": "stop",
            "error_code": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(SSHNativeTransport, "request", simulated_model)
    for cancelled in (False, True):
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        response = await api.post("/api/autoeval/v1/runs", json=body, headers=headers)
        assert response.status_code == 202, response.text
        run_id = response.json()["data"]["run_id"]
        assert (await api.post("/api/autoeval/v1/runs", json=body, headers=headers)).json()["data"][
            "run_id"
        ] == run_id
        async with app.state.sessions() as session:
            snapshot = await session.scalar(
                select(RunSnapshot).where(RunSnapshot.run_id == uuid.UUID(run_id))
            )
            assert snapshot.canonical_body["resource_kind"] == "customer_ssh"
            assert "credential_ref" not in json.dumps(snapshot.canonical_body)
            assert "api_key" not in json.dumps(snapshot.canonical_body)
            assert "container_id" not in snapshot.canonical_body
        if cancelled:
            await api.post(f"/api/autoeval/v1/runs/{run_id}/cancel")
        for _ in range(30):
            if not await deliver_once(app.state.sessions, client):
                break
        detail = await wait_terminal(api, run_id)
        assert detail["state"] == ("cancelled" if cancelled else "completed")
        assert detail["report"]["validity"] == ("failed_summary" if cancelled else "complete")
        assert len(calls) == 1


async def test_ssh_started_attempt_recovers_remote_evidence_without_model_request(
    harness, monkeypatch
):
    app, api, client, settings, body = harness

    async def forbid_model(*args):
        raise AssertionError("Recovery must never invoke the model")

    monkeypatch.setattr(SSHNativeTransport, "request", forbid_model)
    response = await api.post(
        "/api/autoeval/v1/runs", json=body, headers={"Idempotency-Key": uuid.uuid4().hex}
    )
    assert response.status_code == 202, response.text
    run_id = uuid.UUID(response.json()["data"]["run_id"])
    async with app.state.sessions() as session, session.begin():
        intent = await session.scalar(
            select(Outbox).where(Outbox.run_id == run_id).with_for_update()
        )
        intent.state = "delivered"
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
    frozen = snapshot.canonical_body
    transport = await ssh_transport(app.state.sessions, settings, frozen)
    bundle = await asyncio.to_thread(
        read_manifest, settings, SimpleNamespace(**frozen["dataset_content"])
    )
    sample_id = frozen["samples"][0]["sample_id"]
    sample = next(s["native_sample"] for s in bundle["samples"] if s["sample_id"] == sample_id)
    for state in ("queued", "preparing", "running"):
        await transition(app.state.sessions, run_id, state)
    attempt_id = await begin_attempt(
        app.state.sessions,
        AttemptInput(
            run_id=run_id,
            dataset_key="GPQA",
            sample_id=sample_id,
            attempt_no=1,
            operation_key="sample:" + sample_id,
        ),
    )
    prompt = await asyncio.to_thread(
        transport.invoke_local, {"operation": "prompt_gpqa_0shot", "sample": sample}
    )
    # Explicit simulated completed tool evidence, never a model request or real score.
    raw = json.dumps(
        {
            "tool_revision": frozen["tool"]["revision"],
            "prompt": prompt["prompt"],
            "state": "succeeded",
            "response": sample["answer"],
            "finish_reason": "stop",
            "error_code": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    ).encode()
    job_root = f"{transport.root}/jobs/{attempt_id}"
    with transport.control.connect() as ssh:
        transport.control.prepare(ssh)
        transport.control.command(
            ssh,
            [
                "python3",
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).mkdir()",
                job_root,
            ],
        )
        with ssh.open_sftp() as sftp:
            with sftp.open(job_root + "/result.json", "wb") as stream:
                stream.write(raw)
            with sftp.open(job_root + "/exit.json", "w") as stream:
                stream.write(
                    json.dumps(
                        {
                            "state": "succeeded",
                            "result_sha256": hashlib.sha256(raw).hexdigest(),
                            "request_sha256": transport.request_digest(
                                evaluation_activity.model_payload(frozen, sample)
                            ),
                        }
                    )
                )
    original = await client.start_workflow(
        GpqaExplorationWorkflow.run,
        str(run_id),
        id=f"demo/run/{run_id}",
        task_queue="never-run-" + uuid.uuid4().hex,
    )
    await original.terminate("SSH recovery fault injection")
    assert await reconcile_gpqa(app.state.sessions, client, settings, run_id) == "recovery_started"
    detail = await wait_terminal(api, str(run_id))
    assert detail["state"] == "completed", detail
    assert detail["report"]["validity"] == "complete"
    async with app.state.sessions() as session:
        records = (
            await session.scalars(
                select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
            )
        ).all()
        assert len(records) == 1 and records[0].state == "succeeded"
