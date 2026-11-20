"""R12 API acceptance using a dedicated PostgreSQL database and fixed results."""

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import asyncpg
import httpx
import pytest
from google.protobuf.duration_pb2 import Duration
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import make_url
from temporalio import activity
from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

from autoeval.catalog.datasets import canonical_manifest, storage
from autoeval.catalog.registry import Asset, AssetVersion
from autoeval.catalog.standard_inputs import digest
from autoeval.entrypoints.api import create_app
from autoeval.entrypoints.dispatcher import deliver_once
from autoeval.evaluation.models import (
    CapacityLease,
    DatasetExecution,
    EvaluationReport,
    ExecutionRound,
    ExecutionShard,
)
from autoeval.evaluation.orchestration import execute
from autoeval.evaluation.workflows import EvaluationFollowUpWorkflow
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.models import EvaluationRun, Outbox, RunSnapshot
from autoeval.planning.planning_observations import case_contract
from autoeval.reporting.models import CaseExecutionRecord
from autoeval.reporting.unified_outputs import archive_output
from autoeval.resources.models import TargetBinding


async def execute_with_temporal(sessions, settings, run_id, round_id):
    namespace = "autoeval-r12-" + uuid.uuid4().hex[:12]
    address = "127.0.0.1:7233"
    admin = await Client.connect(address)
    await admin.workflow_service.register_namespace(
        RegisterNamespaceRequest(
            namespace=namespace,
            workflow_execution_retention_period=Duration(seconds=86400),
        )
    )
    client = await Client.connect(address, namespace=namespace)

    @activity.defn(name="execute_planned_evaluation")
    async def follow_up(identifier: str, execution_round: str):
        assert (identifier, execution_round) == (str(run_id), str(round_id))
        await execute(
            sessions,
            settings,
            uuid.UUID(identifier),
            activity.heartbeat,
            round_id=uuid.UUID(execution_round),
        )

    async with (
        Worker(client, task_queue="demo.workflow.v1", workflows=[EvaluationFollowUpWorkflow]),
        Worker(client, task_queue="demo.planning-execution.v1", activities=[follow_up]),
    ):
        async with sessions() as session, session.begin():
            intent = (await session.scalars(select(Outbox))).one()
            intent.state = "pending"
            intent.next_retry_at = datetime.now(UTC)
        assert await deliver_once(sessions, client, run_id=run_id)
        handle = client.get_workflow_handle(f"demo/run/{run_id}/round/{round_id}")
        await asyncio.wait_for(handle.result(), 30)


@pytest.mark.skipif(not os.getenv("AE_INFRA_TEST"), reason="Requires isolated PostgreSQL")
@pytest.mark.parametrize(
    "live_storage",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(
                not os.getenv("AE_R12_S3_TEST"), reason="Explicit local S3 acceptance required"
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    "interrupted", [False, True], ids=["inflight-succeeded", "inflight-aborted"]
)
async def test_cancelled_scope_and_conflicting_confirmations(
    monkeypatch, live_storage, interrupted
):
    source = make_url(get_settings().database_url.get_secret_value())
    database = f"autoeval_r12_test_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(
        host=source.host,
        port=source.port or 5432,
        user=source.username,
        password=source.password,
        database=source.database,
    )
    await admin.execute(f'CREATE DATABASE "{database}"')
    settings = get_settings().model_copy(
        update={
            "database_url": SecretStr(
                source.set(database=database).render_as_string(hide_password=False)
            ),
            "evaluation_follow_up_enabled": True,
            "billing_execution_config": None,
            "allowed_model_hosts": ["fixture.invalid"],
            "s3_bucket": f"autoeval-r12-test-{uuid.uuid4().hex}",
        }
    )
    app = create_app(settings)
    run_id = uuid.uuid4()
    target_id = uuid.uuid4()
    initial_completed = ["0", "3", "4", "5"]
    terminal_dispatched = [*initial_completed, "6"]
    initial_reusable = initial_completed if interrupted else terminal_dispatched
    last_shard_ids = ["6", "7", "8", "9"] if interrupted else ["7", "8", "9"]
    task = {
        "task_id": "GPQA",
        "dataset": "GPQA",
        "attempts": 1,
        "concurrency": 1,
        "manifest_id": str(uuid.uuid4()),
        "manifest_sha256": "b" * 64,
        "compilation_id": str(uuid.uuid4()),
        "tool": {},
        "subset_scope": "lite",
        "samples": [
            {"sample_id": f"q{i}", "tool_case_id": str(i), "sha256": digest({"fixture": i})}
            for i in range(10)
        ],
        "compilation": {"config": {"subcommand": "llm_accuracy", "params": {"abbr": "test"}}},
    }
    other_resource = str(uuid.uuid4())
    other_task = {
        **task,
        "task_id": "DeepSWE",
        "dataset": "DeepSWE",
        "samples": [{"sample_id": "q0", "tool_case_id": "other-q0", "sha256": "b" * 64}],
        "compilation": {"config": {"subcommand": "harbor_agent", "params": {}}},
        "assigned_resource_id": other_resource,
        "assigned_resource_kind": "customer_ssh",
    }
    frozen = {
        "inputs": {
            "tasks": [task, other_task],
            "target_id": str(target_id),
            "dataset_concurrency": 3,
            "target": {"model": "fixture", "base_url": "https://fixture.invalid"},
        },
        "resource": {"node_id": "fixture", "cpu_cores": 8, "mem_mb": 16000, "disk_gb": 100},
        "execution_origin": "real",
    }
    objects = {}
    submitted = {}
    submission_calls = []
    active_submissions = set()
    cleanup_attempts = {}
    cancel_during_cleanup = False
    later_retry_failed = False
    other_resource_available = True

    def result_for(ids, *, original=False, aborted=False):
        cases = [
            {"dataset": "GPQA", "case_id": native_id, "attempt": 1, "status": "success", "score": 0}
            for native_id in ids
        ]
        for case in cases:
            if original and case["case_id"] == "0":
                case["score"] = 1
            if (aborted and case["case_id"] == "6") or later_retry_failed:
                case.update(status="failed", score=None)
        return {
            "schema_version": 1,
            "tool": "ais_bench",
            "subcommand": "llm_accuracy",
            "cases": cases,
            "case_count": len(cases),
        }

    class Storage:
        def put_object(self, *, Key, Body, **_):
            objects[Key] = Body

        def get_object(self, *, Key, **_):
            return {"Body": BytesIO(objects[Key])}

        def close(self):
            pass

    class Executor:
        async def submit(self, spec, key):
            assert not active_submissions, "Same dataset shards must retain frozen case concurrency"
            submission_calls.append(key)
            active_submissions.add(key)
            submitted[key] = spec["case_contract"]["sample_ids"]
            if len(submission_calls) == 1:
                raise TimeoutError("Lost acknowledgement after remote submission")

        async def status(self, job):
            active_submissions.discard(job.submission_key)
            return SimpleNamespace(state="succeeded")

        async def cancel(self, job, _operation_key):
            assert job.submission_key == str(job_id)
            return SimpleNamespace(state="cancelled", reason=None)

        async def collect(self, job):
            original = job.submission_key == str(job_id)
            result = {
                "result": {
                    "unified_result": result_for(
                        terminal_dispatched if original else submitted[job.submission_key],
                        original=original,
                        aborted=original and interrupted,
                    )
                }
            }
            if original:
                result["sample_dispatch"] = {
                    "case_contract": case_contract(task),
                    "dispatched": terminal_dispatched,
                }
            return result

        async def cleanup(self, job):
            key = job.submission_key
            cleanup_attempts[key] = cleanup_attempts.get(key, 0) + 1
            if key == str(job_id) and cleanup_attempts[key] == 1:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    original_url = f"/api/autoeval/v1/evaluation-tasks/{run_id}"
                    waiting = (await client.get(f"{original_url}/resume-preview")).json()["data"]
                    assert "cleanup_pending" in waiting["blockers"]
                    assert "samples_unresolved" not in waiting["blockers"]
                    response = await client.post(
                        f"{original_url}/resume",
                        json={k: waiting[k] for k in ("source_round", "scope_sha256")},
                        headers={"Idempotency-Key": "cleanup-still-pending"},
                    )
                    assert response.status_code == 409
            if cancel_during_cleanup and len(submitted) == 3 and cleanup_attempts[key] == 1:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        f"/api/autoeval/v1/evaluation-tasks/{run_id}/cancel"
                    )
                assert response.status_code == 202
                assert response.json()["data"]["accepted"]
            return {"cleaned": cleanup_attempts[key] > 1}

    async def fixture_adapter(_session, _settings, inputs):
        if inputs.get("resource_id") == other_resource:
            assert other_resource_available, "An unrelated resource must not be contacted"
        return Executor()

    if not live_storage:
        monkeypatch.setattr("autoeval.catalog.datasets.storage", lambda _: Storage())
    monkeypatch.setattr("autoeval.evaluation.orchestration.transport", fixture_adapter)
    monkeypatch.setattr(
        "autoeval.evaluation.orchestration.FileSecretStore.get", lambda *_: "fixture-secret"
    )
    job_id = uuid.uuid4()
    s3 = None
    bucket_created = False
    try:
        if live_storage:
            assert urlsplit(settings.s3_endpoint).hostname in {"127.0.0.1", "localhost", "::1"}
            s3 = storage(settings)
            s3.create_bucket(Bucket=settings.s3_bucket)
            bucket_created = True
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "AE_DATABASE_URL": settings.database_url.get_secret_value()},
            check=True,
            timeout=30,
        )
        async with app.router.lifespan_context(app):
            async with app.state.sessions() as session, session.begin():
                model = Asset(asset_key="r12-model", kind="model", name="R12 model")
                session.add(model)
                await session.flush()
                version = AssetVersion(asset_id=model.id, version="test", metadata_json={})
                session.add(version)
                await session.flush()
                session.add(
                    TargetBinding(
                        id=target_id,
                        model_version_id=version.id,
                        base_url="https://fixture.invalid",
                        remote_model="fixture",
                        credential_ref="fixture",
                    )
                )
                session.add(
                    EvaluationRun(
                        id=run_id,
                        trigger_scope="local-operator:orchestration",
                        idempotency_key="fixture",
                        request_hash="hash",
                        state="cancelling",
                        run_mode="exploration",
                        created_by="local-operator",
                        cancel_requested_at=datetime.now(UTC),
                    )
                )
                await session.flush()
                session.add(
                    RunSnapshot(
                        run_id=run_id,
                        schema_version="planned-run.v1",
                        canonical_body=frozen,
                        sha256=digest(frozen),
                    )
                )
                session.add(
                    DatasetExecution(
                        id=job_id,
                        run_id=run_id,
                        task_id="GPQA",
                        state="running",
                        payload=task,
                        started_at=datetime.now(UTC),
                    )
                )
                session.add(CapacityLease(owner_id=job_id, node_id="fixture", demand={}))
                session.add(
                    DatasetExecution(
                        run_id=run_id,
                        task_id="DeepSWE",
                        state="succeeded",
                        payload=other_task,
                        started_at=datetime.now(UTC),
                        finished_at=datetime.now(UTC),
                    )
                )

            seeded = result_for(initial_completed, original=True)
            for case in seeded["cases"]:
                case["case_id"] = "q" + case["case_id"]
            await archive_output(
                app.state.sessions,
                settings,
                run_id,
                "fixture-before-cancellation",
                canonical_manifest(seeded),
                {"GPQA": [sample["sample_id"] for sample in task["samples"]]},
                "GPQA",
            )
            await archive_output(
                app.state.sessions,
                settings,
                run_id,
                "DeepSWE",
                canonical_manifest(
                    {
                        "schema_version": 1,
                        "tool": "ais_bench",
                        "subcommand": "harbor_agent",
                        "case_count": 1,
                        "cases": [
                            {
                                "dataset": "DeepSWE",
                                "case_id": "q0",
                                "attempt": 1,
                                "status": "success",
                                "score": 1,
                            },
                        ],
                    }
                ),
                {"DeepSWE": ["q0"]},
                "DeepSWE",
            )

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                base = f"/api/autoeval/v1/evaluation-tasks/{run_id}"
                blocked = (await client.get(f"{base}/resume-preview")).json()["data"]
                assert {"cleanup_pending", "samples_unresolved"} <= set(blocked["blockers"])
                refused = await client.post(
                    f"{base}/resume",
                    json={k: blocked[k] for k in ("source_round", "scope_sha256")},
                    headers={"Idempotency-Key": "blocked"},
                )
                assert refused.status_code == 409
                await execute(app.state.sessions, settings, run_id)
                other_resource_available = False
                assert not submitted
                initial = (await client.get(f"{base}/resume-preview")).json()["data"]
                assert not initial["blockers"]
                assert initial["sample_count"] == 10 - len(initial_reusable)
                assert {
                    row["sample_id"] for row in initial["samples"] if row["category"] == "reusable"
                } == {f"q{i}" for i in initial_reusable}

                target = {"dataset_key": "GPQA", "sample_id": "q2"}
                preview = (await client.get(f"{base}/case-retry-preview", params=target)).json()[
                    "data"
                ]
                assert preview["sample_count"] == 1
                assert not preview["blockers"]
                body = {**target, **{k: preview[k] for k in ("source_round", "scope_sha256")}}
                responses = await asyncio.gather(
                    *(
                        client.post(
                            f"{base}/case-retry", json=body, headers={"Idempotency-Key": key}
                        )
                        for key in ("first", "second")
                    )
                )
                assert [response.status_code for response in responses] == [202, 202]
                assert responses[0].json()["data"] == responses[1].json()["data"]
                conflict = await client.post(
                    f"{base}/case-retry",
                    json={**body, "sample_id": "q1"},
                    headers={"Idempotency-Key": "first"},
                )
                assert conflict.status_code == 409
                competing_resume = await client.post(
                    f"{base}/resume",
                    json={k: initial[k] for k in ("source_round", "scope_sha256")},
                    headers={"Idempotency-Key": "competing-resume"},
                )
                assert competing_resume.status_code == 409
            async with app.state.sessions() as session:
                assert len(list(await session.scalars(select(ExecutionRound)))) == 1
                assert len(list(await session.scalars(select(Outbox)))) == 1
                shard = (await session.scalars(select(ExecutionShard))).one()
                assert [row["sample_id"] for row in shard.payload["samples"]] == ["q2"]
                assert (
                    shard.payload["compilation"]["config"]["params"]["dataset_test_range"]
                    == "[2:3]"
                )
                round_id = shard.round_id
            workflow_starts = []

            class Temporal:
                async def start_workflow(self, workflow, payload, **options):
                    workflow_starts.append((workflow, payload, options["id"]))
                    if len(workflow_starts) == 1:
                        raise TimeoutError("Simulated acknowledgement loss")
                    raise WorkflowAlreadyStartedError(options["id"], "EvaluationFollowUpWorkflow")

            temporal = Temporal()
            assert await deliver_once(app.state.sessions, temporal, run_id=run_id)
            async with app.state.sessions() as session, session.begin():
                intent = (await session.scalars(select(Outbox))).one()
                assert intent.state == "pending"
                intent.next_retry_at = datetime.now(UTC)
            assert await deliver_once(app.state.sessions, temporal, run_id=run_id)
            assert workflow_starts[0] == workflow_starts[1]
            assert workflow_starts[0][1:] == (
                {"run_id": str(run_id), "round_id": str(round_id)},
                f"demo/run/{run_id}/round/{round_id}",
            )
            async with app.state.sessions() as session:
                intent = (await session.scalars(select(Outbox))).one()
                assert intent.state == "delivered"
            if os.getenv("AE_R12_TEMPORAL_TEST"):
                await execute_with_temporal(app.state.sessions, settings, run_id, round_id)
            else:
                await execute(app.state.sessions, settings, run_id, round_id=round_id)
            await execute(app.state.sessions, settings, run_id, round_id=round_id)
            assert list(submitted.values()) == [{"2": "q2"}]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                report = (await client.get(f"{base}/report")).json()["data"]
                assert report["round"] == 2
                assert report["datasets"][0]["summary"]["expected_samples"] == 10
                assert report["datasets"][1]["summary"]["accuracy"] == 100
                assert report["summary"]["missing_samples"] == 4
                assert report["historical_task_state"] == "cancelled"
                preview = (await client.get(f"{base}/resume-preview")).json()["data"]
                assert preview["sample_count"] == 1 + len(last_shard_ids)
                assert {
                    row["sample_id"] for row in preview["samples"] if row["category"] == "remaining"
                } == {"q1", *(f"q{i}" for i in last_shard_ids)}
                resumed = await client.post(
                    f"{base}/resume",
                    json={k: preview[k] for k in ("source_round", "scope_sha256")},
                    headers={"Idempotency-Key": "resume"},
                )
                assert resumed.status_code == 202
            async with app.state.sessions() as session:
                next_round = await session.scalar(
                    select(ExecutionRound).where(ExecutionRound.number == 3)
                )
                next_id = next_round.id
            cancel_during_cleanup = True
            await execute(app.state.sessions, settings, run_id, round_id=next_id)
            assert list(submitted.values()) == [
                {"2": "q2"},
                {"1": "q1"},
                {i: f"q{i}" for i in last_shard_ids},
            ]
            assert cleanup_attempts == dict.fromkeys([str(job_id), *submitted], 2)
            assert submission_calls == list(submitted)
            async with app.state.sessions() as session:
                versions = list(
                    await session.scalars(
                        select(EvaluationReport).order_by(EvaluationReport.version)
                    )
                )
                assert [(row.version, row.is_current) for row in versions] == [
                    (1, False),
                    (2, False),
                    (3, True),
                ]
                assert versions[0].summary["missing_samples"] == 5
                assert versions[1].summary["missing_samples"] == 4
                assert versions[1].summary["failed_samples"] == int(interrupted)
                assert versions[2].summary["missing_samples"] == 0
                assert versions[2].summary["expected_samples"] == 11
                assert versions[2].summary["dataset_results"][0]["summary"]["accuracy"] == 10
            async with app.state.sessions() as session, session.begin():
                assert (await session.get_one(EvaluationRun, run_id)).state == "cancelled"
                target_row = await session.get_one(TargetBinding, target_id)
                target_row.remote_model = "different-model"

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                preview = (await client.get(f"{base}/resume-preview")).json()["data"]
                assert preview["sample_count"] == 0
                assert not preview["blockers"]
                assert all(row["category"] == "reusable" for row in preview["samples"])
                resumed = await client.post(
                    f"{base}/resume",
                    json={k: preview[k] for k in ("source_round", "scope_sha256")},
                    headers={"Idempotency-Key": "report-only"},
                )
                assert resumed.status_code == 202
            async with app.state.sessions() as session:
                report_round = await session.scalar(
                    select(ExecutionRound).where(ExecutionRound.number == 4)
                )
                report_round_id = report_round.id

            async def unavailable_transport(*_):
                pytest.fail("An all-reused round must not connect to an executor")

            monkeypatch.setattr(
                "autoeval.evaluation.orchestration.transport", unavailable_transport
            )
            async with app.state.sessions() as session:
                evidence_key = await session.scalar(
                    select(CaseExecutionRecord.object_key).where(
                        CaseExecutionRecord.run_id == run_id,
                        CaseExecutionRecord.sample_id == "q0",
                        CaseExecutionRecord.dataset_key == "GPQA",
                    )
                )
            if s3 is not None:
                with s3.get_object(Bucket=settings.s3_bucket, Key=evidence_key)["Body"] as stream:
                    saved = stream.read()
                s3.put_object(Bucket=settings.s3_bucket, Key=evidence_key, Body=b"corrupt evidence")
            else:
                saved = objects[evidence_key]
                objects[evidence_key] = b"corrupt evidence"
            await execute(app.state.sessions, settings, run_id, round_id=report_round_id)
            async with app.state.sessions() as session:
                assert (await session.get_one(ExecutionRound, report_round_id)).state == "cancelled"
                assert (await session.get_one(EvaluationRun, run_id)).state == "cancelled"
            if s3 is not None:
                s3.put_object(Bucket=settings.s3_bucket, Key=evidence_key, Body=saved)
            else:
                objects[evidence_key] = saved
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                refreshed = (await client.get(f"{base}/resume-preview")).json()["data"]
                assert refreshed["source_round"] == 4 and refreshed["sample_count"] == 0
                replacement_response = await client.post(
                    f"{base}/resume",
                    json={k: refreshed[k] for k in ("source_round", "scope_sha256")},
                    headers={"Idempotency-Key": "report-after-recheck"},
                )
                assert replacement_response.status_code == 202
            async with app.state.sessions() as session:
                replacement = await session.scalar(
                    select(ExecutionRound.id).where(ExecutionRound.number == 5)
                )
            await execute(app.state.sessions, settings, run_id, round_id=replacement)
            async with app.state.sessions() as session:
                current = await session.scalar(
                    select(EvaluationReport).where(EvaluationReport.is_current)
                )
                assert current.version == 5 and current.summary["missing_samples"] == 0
                assert (await session.get_one(EvaluationRun, run_id)).state == "completed"
            assert len(submitted) == 3
            cancel_during_cleanup = False
            monkeypatch.setattr("autoeval.evaluation.orchestration.transport", fixture_adapter)
            async with app.state.sessions() as session, session.begin():
                (await session.get_one(TargetBinding, target_id)).remote_model = "fixture"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                original_report = (await client.get(f"{base}/report")).json()["data"]
                original_index = original_report["datasets"][0]["case_index"]
                target = {"dataset_key": "GPQA", "sample_id": "q0"}
                for number, expected_accuracy in ((6, 0), (7, None)):
                    later_retry_failed = number == 7
                    preview = (
                        await client.get(f"{base}/case-retry-preview", params=target)
                    ).json()["data"]
                    assert preview["source_round"] == number - 1 and not preview["blockers"]
                    response = await client.post(
                        f"{base}/case-retry",
                        json={
                            **target,
                            **{k: preview[k] for k in ("source_round", "scope_sha256")},
                        },
                        headers={"Idempotency-Key": f"repeat-q0-{number}"},
                    )
                    assert response.status_code == 202
                    async with app.state.sessions() as session:
                        retry_id = await session.scalar(
                            select(ExecutionRound.id).where(ExecutionRound.number == number)
                        )
                    await execute(app.state.sessions, settings, run_id, round_id=retry_id)
                    latest = (await client.get(f"{base}/report")).json()["data"]
                    detail = (await client.get(base)).json()["data"]
                    assert detail["current_round"] == number
                    assert detail["datasets"][0]["summary"] == latest["datasets"][0]["summary"]
                    result = latest["datasets"][0]
                    assert result["summary"]["accuracy"] == expected_accuracy
                    assert result["summary"]["failed_samples"] == int(later_retry_failed)
                    assert result["case_index"][1:] == original_index[1:]
                    assert result["case_index"][0] != original_index[0]
                    assert latest["datasets"][1] == original_report["datasets"][1]
                assert list(submitted.values())[-2:] == [{"0": "q0"}, {"0": "q0"}]
                replay = await client.post(
                    f"{base}/case-retry", json=body, headers={"Idempotency-Key": "first"}
                )
                assert replay.status_code == 202
                assert replay.json()["data"]["round"] == 2
                async with app.state.sessions() as session:
                    assert len(list(await session.scalars(select(ExecutionRound)))) == 6
                    attempts = list(
                        await session.scalars(
                            select(CaseExecutionRecord)
                            .where(
                                CaseExecutionRecord.run_id == run_id,
                                CaseExecutionRecord.sample_id == "q0",
                                CaseExecutionRecord.dataset_key == "GPQA",
                            )
                            .order_by(CaseExecutionRecord.attempt_no)
                        )
                    )
                    assert [(row.attempt_no, row.state) for row in attempts] == [
                        (1, "succeeded"),
                        (2, "succeeded"),
                        (3, "failed"),
                    ]
    finally:
        try:
            if bucket_created:
                paginator = s3.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=settings.s3_bucket):
                    for entry in page.get("Contents", []):
                        s3.delete_object(Bucket=settings.s3_bucket, Key=entry["Key"])
                s3.delete_bucket(Bucket=settings.s3_bucket)
        finally:
            if s3 is not None:
                s3.close()
            await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
            await admin.close()
