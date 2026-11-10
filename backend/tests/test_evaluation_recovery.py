import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from autoeval import case_history, evaluation_activity, reconciler
from autoeval.audit import AuditEvent
from autoeval.case_history import (
    AttemptEvidence,
    AttemptInput,
    CaseExecutionRecord,
    begin_attempt,
    finish_attempt,
)
from autoeval.config import Settings
from autoeval.datasets import canonical_manifest
from autoeval.evaluations import EvaluationReport
from autoeval.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.registry import Asset, AssetVersion
from autoeval.run_activities import transition
from autoeval.runs import ExecutionLease
from autoeval.secrets import FileSecretStore
from autoeval.targets import TargetBinding
from autoeval.workflows import GpqaExplorationWorkflow


@pytest.fixture
async def recovery_harness(monkeypatch, tmp_path):
    settings = Settings(
        environment="test", evaluation_origin="simulation", secret_store_path=tmp_path
    )
    engine = create_async_engine(settings.database_url.get_secret_value())
    connection = await engine.connect()
    transaction = await connection.begin()
    sessions = async_sessionmaker(
        connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    objects = {}

    def read_manifest(_settings, row):
        raw = objects.get(row.object_key)
        if raw is None or hashlib.sha256(raw).hexdigest() != row.sha256:
            raise ValueError("Evidence missing or corrupt")
        return json.loads(raw)

    def write_manifest(_settings, key, raw):
        objects[key] = raw

    activity_engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(evaluation_activity, "get_settings", lambda: settings)
    monkeypatch.setattr(
        evaluation_activity, "create_database", lambda _settings: (activity_engine, sessions)
    )
    monkeypatch.setattr(evaluation_activity, "read_manifest", read_manifest)
    monkeypatch.setattr(evaluation_activity, "write_manifest", write_manifest)
    monkeypatch.setattr(case_history, "read_manifest", read_manifest)
    monkeypatch.setattr(case_history, "write_manifest", write_manifest)
    monkeypatch.setattr(
        evaluation_activity,
        "inspect_executor",
        lambda _executable, _container: {"running": True, "image_id": "image-test"},
    )
    monkeypatch.setattr(activity, "heartbeat", lambda _run_id: None)
    try:
        yield SimpleNamespace(
            settings=settings, sessions=sessions, objects=objects, read_manifest=read_manifest
        )
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def make_run(harness, sample_count=2):
    sessions = harness.sessions
    credential_ref = FileSecretStore(harness.settings.secret_store_path).put("fixture-only")
    async with sessions() as session, session.begin():
        asset = Asset(asset_key="model-" + uuid.uuid4().hex, kind="model", name="Fixture model")
        session.add(asset)
        await session.flush()
        version = AssetVersion(asset_id=asset.id, version="v1", metadata_json={})
        session.add(version)
        await session.flush()
        target = TargetBinding(
            model_version_id=version.id,
            base_url="https://api.deepseek.com",
            remote_model="deepseek-flash",
            credential_ref=credential_ref,
        )
        session.add(target)
        await session.flush()
        run = EvaluationRun(
            trigger_scope="local-operator:evaluation",
            idempotency_key=uuid.uuid4().hex,
            request_hash="a" * 64,
            run_mode="exploration",
            created_by="recovery-test",
            state="running",
        )
        session.add(run)
        await session.flush()
        natives = [
            {"sample_id": f"sample-{index}", "question": f"question-{index}", "answer": "A"}
            for index in range(1, sample_count + 1)
        ]
        samples = [
            {
                "sample_id": native["sample_id"],
                "sha256": hashlib.sha256(canonical_manifest(native)).hexdigest(),
                "native_sample": native,
            }
            for native in natives
        ]
        bundle = {"samples": samples}
        bundle_raw = canonical_manifest(bundle)
        bundle_key = "fixture-dataset-" + uuid.uuid4().hex
        harness.objects[bundle_key] = bundle_raw
        frozen = {
            "execution_origin": "simulation",
            "schema_version": "gpqa-run.v1",
            "target_id": str(target.id),
            "container_id": "c" * 64,
            "image_id": "image-test",
            "base_url": target.base_url,
            "remote_model": target.remote_model,
            "parameters": {"output": 32},
            "tool": {"revision": "tool-test"},
            "samples": [
                {"sample_id": sample["sample_id"], "sha256": sample["sha256"]}
                for sample in samples
            ],
            "dataset_content": {
                "object_key": bundle_key,
                "sha256": hashlib.sha256(bundle_raw).hexdigest(),
                "sample_count": sample_count,
            },
        }
        snapshot = RunSnapshot(
            run_id=run.id,
            schema_version="gpqa-run.v1",
            canonical_body=frozen,
            sha256=hashlib.sha256(canonical_manifest(frozen)).hexdigest(),
        )
        session.add(snapshot)
        session.add(ExecutionLease(container_id="c" * 64, run_id=run.id))
        session.add(RunEvent(run_id=run.id, seq=1, type="accepted", body={}))
    return run, snapshot


async def archive_first_attempt(harness, run):
    attempt_id = await begin_attempt(
        harness.sessions,
        AttemptInput(
            run_id=run.id,
            dataset_key="GPQA",
            sample_id="sample-1",
            attempt_no=1,
            operation_key="sample:sample-1",
        ),
    )
    await finish_attempt(
        harness.sessions,
        harness.settings,
        attempt_id,
        AttemptEvidence(
            state="succeeded", prompt="archived prompt", response="A", finish_reason="stop"
        ),
    )
    return attempt_id


async def test_archived_attempt_resumes_next_sample_and_terminal_replay_is_idempotent(
    recovery_harness, monkeypatch
):
    harness = recovery_harness
    run, _snapshot = await make_run(harness)
    first_id = await archive_first_attempt(harness, run)
    infer_samples = []
    scoring = []

    def fake_invoke(_settings, _container_id, payload):
        if payload["operation"] == "prompt_gpqa_0shot":
            return {"prompt": "new prompt", "tool_revision": "tool-test"}
        if payload["operation"] == "score_gpqa_0shot":
            scoring.append(payload)
            return {"native_result": {"accuracy": 100}}
        infer_samples.append(payload["sample"]["sample_id"])
        return {
            "state": "succeeded",
            "response": "A",
            "finish_reason": "stop",
            "error_code": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(evaluation_activity, "invoke", fake_invoke)

    assert await evaluation_activity.execute_gpqa_exploration(str(run.id), resume=True) == {
        "state": "completed",
        "validity": "complete",
    }
    assert infer_samples == ["sample-2"]
    assert scoring[0]["predictions"] == ["A", "A"]
    assert scoring[0]["references"] == ["A", "A"]

    async with harness.sessions() as session:
        attempts = (
            await session.scalars(
                select(CaseExecutionRecord)
                .where(CaseExecutionRecord.run_id == run.id)
                .order_by(CaseExecutionRecord.sample_id)
            )
        ).all()
        report = await session.scalar(select(EvaluationReport).where(EvaluationReport.run_id == run.id))
        events = (
            await session.scalars(select(RunEvent).where(RunEvent.run_id == run.id))
        ).all()
        assert [attempt.sample_id for attempt in attempts] == ["sample-1", "sample-2"]
        assert report.summary["executed_attempts"] == 2
        assert report.summary["missing_samples"] == 0
        report_id, report_key = report.id, report.object_key
        event_count = len(attempts), len(events)
        first_evidence = harness.objects[attempts[0].object_key]
        assert json.loads(report and harness.objects[report.object_key])["attempts"][0][
            "attempt_id"
        ] == str(first_id)
        assert await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == run.id)) is None

    object_count = len(harness.objects)
    assert await evaluation_activity.execute_gpqa_exploration(str(run.id), resume=True) == {
        "state": "completed"
    }
    assert infer_samples == ["sample-2"]
    assert len(scoring) == 1
    assert len(harness.objects) == object_count
    async with harness.sessions() as session:
        assert (await session.get(EvaluationReport, report_id)).object_key == report_key
        assert (
            len((await session.scalars(select(RunEvent).where(RunEvent.run_id == run.id))).all())
            == event_count[1]
        )
    assert harness.objects[attempts[0].object_key] == first_evidence

    verified_reports = []

    def tracking_read(settings, row):
        data = harness.read_manifest(settings, row)
        if row.object_key == report_key:
            verified_reports.append(row.object_key)
        return data

    monkeypatch.setattr(evaluation_activity, "read_manifest", tracking_read)
    assert await evaluation_activity.execute_gpqa_exploration(str(run.id), resume=True) == {
        "state": "completed"
    }
    assert verified_reports == [report_key]
    client = FakeTemporalClient(WorkflowExecutionStatus.COMPLETED)
    assert await reconciler.reconcile_gpqa(
        harness.sessions, client, harness.settings, run.id
    ) == "terminal"
    assert client.starts == []
    assert len(harness.objects) == object_count
    assert len(scoring) == 1
    async with harness.sessions() as session:
        assert (await session.get(EvaluationReport, report_id)).object_key == report_key
        assert (
            len((await session.scalars(select(RunEvent).where(RunEvent.run_id == run.id))).all())
            == event_count[1]
        )


async def test_existing_report_with_nonterminal_run_is_verified_not_overwritten(
    recovery_harness, monkeypatch
):
    harness = recovery_harness
    run, snapshot = await make_run(harness)
    first_id = await archive_first_attempt(harness, run)
    await transition(harness.sessions, run.id, "aggregating")
    summary = {
        "expected_samples": 2,
        "executed_attempts": 1,
        "successful_samples": 1,
        "failed_samples": 0,
        "missing_samples": 1,
        "cancelled": False,
    }
    raw = canonical_manifest(
        {
            "schema_version": "gpqa-report.v1",
            "execution_origin": "simulation",
            "run_id": str(run.id),
            "snapshot_sha256": snapshot.sha256,
            "validity": "partial",
            "summary": summary,
            "attempts": [
                {
                    "sample_id": "sample-1",
                    "attempt_id": str(first_id),
                    "state": "succeeded",
                    "usage": None,
                }
            ],
            "native_scoring": None,
        }
    )
    digest = hashlib.sha256(raw).hexdigest()
    key = f"reports/{run.id}/{digest}.json"
    harness.objects[key] = raw
    async with harness.sessions() as session, session.begin():
        report = EvaluationReport(
            run_id=run.id,
            execution_origin="simulation",
            validity="partial",
            snapshot_sha256=snapshot.sha256,
            summary=summary,
            object_key=key,
            sha256=digest,
        )
        session.add(report)
        await session.flush()
        report_id = report.id

    def forbidden_invoke(*_args, **_kwargs):
        raise AssertionError("An existing report must not cause more execution")

    monkeypatch.setattr(evaluation_activity, "invoke", forbidden_invoke)
    assert await evaluation_activity.execute_gpqa_exploration(str(run.id), resume=True) == {
        "state": "unresolved",
        "ownership_retained": True,
    }
    async with harness.sessions() as session:
        current = await session.get(EvaluationReport, report_id)
        assert current.object_key == key
        assert current.sha256 == digest
        assert harness.objects[key] == raw
        assert await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == run.id))
        current_run = await session.get(EvaluationRun, run.id)
        assert current_run.state == "aggregating"


class FakeTemporalClient:
    def __init__(self, original_status):
        self.original_status = original_status
        self.recovery_status = None
        self.starts = []

    def get_workflow_handle(self, workflow_id):
        client = self

        class Handle:
            async def describe(self):
                if workflow_id.startswith("demo/run/"):
                    status = client.original_status
                else:
                    if client.recovery_status is None:
                        raise RPCError("Workflow not found", RPCStatusCode.NOT_FOUND, b"")
                    status = client.recovery_status
                return SimpleNamespace(status=status)

        return Handle()

    async def start_workflow(self, workflow, request, *, id, task_queue, **kwargs):
        self.starts.append(
            SimpleNamespace(
                workflow=workflow, request=request, id=id, task_queue=task_queue, kwargs=kwargs
            )
        )
        self.recovery_status = WorkflowExecutionStatus.RUNNING


async def test_started_attempt_blocks_activity_and_reconciliation_without_model_calls(
    recovery_harness, monkeypatch
):
    harness = recovery_harness
    run, _snapshot = await make_run(harness)
    await begin_attempt(
        harness.sessions,
        AttemptInput(
            run_id=run.id,
            dataset_key="GPQA",
            sample_id="sample-1",
            attempt_no=1,
            operation_key="sample:sample-1",
        ),
    )

    def forbidden_invoke(*_args, **_kwargs):
        raise AssertionError("A started attempt must never be resubmitted")

    monkeypatch.setattr(evaluation_activity, "invoke", forbidden_invoke)
    assert await evaluation_activity.execute_gpqa_exploration(str(run.id), resume=True) == {
        "state": "unresolved",
        "ownership_retained": True,
    }
    client = FakeTemporalClient(WorkflowExecutionStatus.COMPLETED)
    assert await reconciler.reconcile_gpqa(
        harness.sessions, client, harness.settings, run.id
    ) == "unresolved"
    assert await reconciler.reconcile_gpqa(
        harness.sessions, client, harness.settings, run.id
    ) == "unresolved"
    assert client.starts == []
    async with harness.sessions() as session:
        current = await session.get(EvaluationRun, run.id)
        assert current.state == "running"
        assert current.projection_version == 2
        assert await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == run.id))
        events = (
            await session.scalars(
                select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)
            )
        ).all()
        assert [event.type for event in events] == ["accepted", "execution_unresolved"]
        assert events[-1].body["ownership_retained"] is True
        audits = (
            await session.scalars(select(AuditEvent).where(AuditEvent.run_id == run.id))
        ).all()
        assert [audit.action for audit in audits] == ["recovery.unresolved"]
        assert audits[0].details["reason"] == "started_attempt"


async def test_active_original_workflow_is_not_raced(recovery_harness):
    harness = recovery_harness
    run, _snapshot = await make_run(harness)
    client = FakeTemporalClient(WorkflowExecutionStatus.RUNNING)

    assert await reconciler.reconcile_gpqa(
        harness.sessions, client, harness.settings, run.id
    ) == "workflow_active"
    assert client.starts == []
    async with harness.sessions() as session:
        current = await session.get(EvaluationRun, run.id)
        assert current.state == "running"
        assert current.projection_version == 1
        assert await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == run.id))
        assert len(
            (await session.scalars(select(RunEvent).where(RunEvent.run_id == run.id))).all()
        ) == 1


async def test_closed_original_uses_stable_resume_workflow_and_skips_active_recovery(
    recovery_harness,
):
    harness = recovery_harness
    run, _snapshot = await make_run(harness)
    await archive_first_attempt(harness, run)
    client = FakeTemporalClient(WorkflowExecutionStatus.COMPLETED)
    recovery_id = f"demo/recovery/gpqa/{run.id}"

    assert await reconciler.reconcile_gpqa(
        harness.sessions, client, harness.settings, run.id
    ) == "recovery_started"
    assert len(client.starts) == 1
    started = client.starts[0]
    assert started.workflow == GpqaExplorationWorkflow.run
    assert started.request == {
        "run_id": str(run.id),
        "activity_queue": harness.settings.gpqa_activity_queue,
        "resume": True,
    }
    assert started.id == recovery_id
    assert started.task_queue == harness.settings.gpqa_workflow_queue
    assert started.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE

    assert await reconciler.reconcile_gpqa(
        harness.sessions, client, harness.settings, run.id
    ) == "recovery_active"
    assert len(client.starts) == 1

    client.recovery_status = WorkflowExecutionStatus.COMPLETED
    assert await reconciler.reconcile_gpqa(
        harness.sessions, client, harness.settings, run.id
    ) == "recovery_started"
    assert [start.id for start in client.starts] == [recovery_id, recovery_id]
    async with harness.sessions() as session:
        current = await session.get(EvaluationRun, run.id)
        assert current.state == "running"
        assert current.projection_version == 1
        assert await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == run.id))
        assert len(
            (await session.scalars(select(RunEvent).where(RunEvent.run_id == run.id))).all()
        ) == 1


async def test_reconciliation_entry_routes_evaluation_runs(recovery_harness):
    harness = recovery_harness
    run, _snapshot = await make_run(harness)
    await archive_first_attempt(harness, run)
    client = FakeTemporalClient(WorkflowExecutionStatus.COMPLETED)

    assert await reconciler.reconcile_run(
        harness.sessions, client, harness.settings, run.id
    ) == "recovery_started"
    assert len(client.starts) == 1

async def test_real_worker_never_resumes_a_simulated_model_request(recovery_harness, monkeypatch):
    harness = recovery_harness
    run, _ = await make_run(harness, sample_count=1)
    harness.settings.evaluation_origin = "real"

    def forbid_inference(*args, **kwargs):
        raise AssertionError("A real Worker must not execute simulated requests")

    monkeypatch.setattr(evaluation_activity, "invoke", forbid_inference)
    result = await evaluation_activity.execute_gpqa_exploration(str(run.id), resume=True)
    assert result["state"] == "unresolved"
    async with harness.sessions() as session:
        row = await session.get(EvaluationRun, run.id)
        assert row.state == "running"
        attempts = (await session.scalars(select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run.id))).all()
        assert not attempts
