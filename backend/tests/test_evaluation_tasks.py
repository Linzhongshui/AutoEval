"""Unified task contracts and isolated real PostgreSQL acceptance; never calls models."""

import asyncio
import copy
import os
import subprocess
import sys
import uuid
from types import SimpleNamespace

import asyncpg
import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from autoeval.catalog.registry import Asset, AssetVersion
from autoeval.entrypoints.api import create_app
from autoeval.evaluation.evaluation_tasks import SubmitTask
from autoeval.evaluation.models import DatasetExecution, DatasetExecutionEnvironment
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.models import Base, EvaluationRun, Outbox, RunSnapshot
from autoeval.planning import PlanningJob
from autoeval.planning.planning_transport import PlanningRemoteContainer
from autoeval.resources.models import ResourceProvider, SSHResourceBinding, TargetBinding


def submission(datasets=("GPQA", "MMMU-Pro")):
    return {
        "target_id": str(uuid.uuid4()),
        "resource_id": str(uuid.uuid4()),
        "resource_kind": "customer_ssh",
        "dataset_concurrency": 2,
        "tasks": [
            {
                "task_id": d.replace("-", "_"),
                "dataset": d,
                "compilation_id": str(uuid.uuid4()),
                "manifest_id": str(uuid.uuid4()),
                "concurrency": 2,
            }
            for d in datasets
        ],
    }


def test_submit_contract_has_only_final_parameters():
    body = submission()
    assert len(SubmitTask(**body).tasks) == 2
    for field in ("execution_plan_id", "throughput_profile_id", "recommend"):
        with pytest.raises(ValidationError):
            SubmitTask(**body, **{field: str(uuid.uuid4())})
    with pytest.raises(ValidationError, match="Duplicate"):
        SubmitTask(**{**body, "tasks": [body["tasks"][0]] * 2})
    legacy = copy.deepcopy(body)
    for task in legacy["tasks"]:
        task.pop("concurrency")
    assert SubmitTask(**legacy).model_dump(mode="json") == legacy


def test_execution_transport_does_not_require_planner(monkeypatch):
    monkeypatch.setattr("autoeval_runtime.planning_runtime.installed_revision", lambda _: None)
    transport = PlanningRemoteContainer(
        SimpleNamespace(workdir="/test", owner_id="test"), "c" * 64, "sha256:" + "d" * 64
    )
    assert "planning_runtime.py" in transport.files
    assert not any(name.startswith("deps/") for name in transport.files)


def test_remote_runtime_can_share_absolute_host_mount(monkeypatch):
    monkeypatch.setattr("autoeval_runtime.planning_runtime.installed_revision", lambda _: None)
    connection = SimpleNamespace(workdir="/test", owner_id="test")
    adapter = PlanningRemoteContainer(
        connection, "c" * 64, "sha256:" + "d" * 64, runtime_root="/acceptance/shared-runtime"
    )
    assert adapter.remote_dir.startswith("/acceptance/shared-runtime/")
    for invalid in ("relative", "/", "/acceptance/../outside"):
        with pytest.raises(ValueError, match="absolute directory"):
            PlanningRemoteContainer(
                connection, "c" * 64, "sha256:" + "d" * 64, runtime_root=invalid
            )


def test_api_starts_without_planner_package():
    script = """
import importlib.abc, sys
class NoPlanner(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('autoeval_planner'):
            raise ModuleNotFoundError('Planner intentionally unavailable', name=fullname)
sys.meta_path.insert(0, NoPlanner())
from autoeval.entrypoints.api import create_app
assert '/api/autoeval/v1/evaluation-tasks' in create_app().openapi()['paths']
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


async def test_final_form_concurrency_cannot_override_scoring_lock(monkeypatch):
    from fastapi import HTTPException

    from autoeval.planning import PlanInput, resolve_inputs

    body = PlanInput(**submission(("GPQA",)))
    compiled = {
        "input_ready": True,
        "adaptor_revision": "955089ab32ef696c231d628f5ad0d9da28f430c4",
        "credential_binding": {"target_id": str(body.target_id)},
        "config": {
            "tool": "ais_bench",
            "subcommand": "llm_accuracy",
            "params": {"datasets": ["gpqa"], "batch_size": 1},
        },
        "locked_fields": {"params.batch_size": 1, "params.max_out_len": 100},
    }

    class Session:
        async def get(self, model, key):
            return {
                "StandardInputCompilation": SimpleNamespace(
                    payload=compiled, input_id=uuid.uuid4()
                ),
                "DatasetManifest": SimpleNamespace(id=key, dataset_version_id=uuid.uuid4()),
                "AssetVersion": SimpleNamespace(asset_id=uuid.uuid4()),
                "Asset": SimpleNamespace(asset_key="GPQA"),
                "StandardInputVersion": SimpleNamespace(benchmark="GPQA_Diamond"),
            }[model.__name__]

        async def scalar(self, query):
            return SimpleNamespace()

    async def target(*args):
        return {"model": "TEST", "base_url": "https://fixture.invalid"}

    monkeypatch.setattr("autoeval.evaluation.inputs.target_data", target)
    with pytest.raises(HTTPException, match="Standard lock conflicts") as exc:
        await resolve_inputs(Session(), get_settings(), body)
    assert exc.value.status_code == 422
    assert compiled["config"]["params"]["batch_size"] == 1


@pytest.mark.skipif(
    not os.getenv("AE_INFRA_TEST"), reason="Explicit PostgreSQL acceptance required"
)
async def test_unified_tasks_isolated_postgres(monkeypatch):
    # Dedicated temporary DB: the running development dispatcher cannot see these intents.
    source = make_url(get_settings().database_url.get_secret_value())
    database = "autoeval_tasks_test_" + uuid.uuid4().hex
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
            "evaluation_origin": "real",
            "allowed_model_hosts": ["fixture.invalid"],
        }
    )
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            async with app.state.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with app.state.sessions() as session, session.begin():
                asset = Asset(asset_key="test-model", kind="model", name="Test model")
                session.add(asset)
                await session.flush()
                version = AssetVersion(asset_id=asset.id, version="test", metadata_json={})
                session.add(version)
                await session.flush()
                target = TargetBinding(
                    model_version_id=version.id,
                    base_url="https://fixture.invalid",
                    remote_model="acceptance-model",
                    credential_ref="0" * 32,
                )
                session.add(target)
                await session.flush()
                target_id = str(target.id)
                provider = ResourceProvider(name="R13 PostgreSQL fixture", kind="customer_ssh")
                session.add(provider)
                await session.flush()
                resource = SSHResourceBinding(
                    provider_id=provider.id,
                    binding_key="r13-fixture",
                    version=1,
                    host="fixture.invalid",
                    port=22,
                    username="tester",
                    fingerprint="SHA256:" + "a" * 43,
                    workdir="/work",
                    auth_kind="private_key",
                    credential_ref="0" * 32,
                )
                session.add(resource)
                await session.flush()
                resource_id = str(resource.id)

            template = {"family": "aisbench", "revision": "test", "image_id": "sha256:" + "a" * 64}

            async def resolve(session, settings, body):
                inputs = body.model_dump(mode="json")
                for t in inputs["tasks"]:
                    t.update(
                        concurrency=t.get("concurrency") or 1,
                        assigned_resource_id=inputs["resource_id"],
                        assigned_resource_kind=inputs["resource_kind"],
                        execution_template={
                            **template,
                            "family": "harbor"
                            if t["dataset"] in {"DeepSWE", "AutomationBench"}
                            else "aisbench",
                        },
                        samples=[{"sample_id": "0", "tool_case_id": "0"}],
                        manifest_sha256="a" * 64,
                        tool={},
                        subset_scope="lite",
                        compilation={
                            "config": {"params": {"batch_size": t.get("concurrency") or 1}}
                        },
                    )
                return inputs

            async def preflight(session, inputs, **kwargs):
                return SimpleNamespace(
                    sha256="b" * 64,
                    payload={
                        "execution_ready": True,
                        "execution_templates": {
                            task["task_id"]: task["execution_template"] for task in inputs["tasks"]
                        },
                        "planner_ready": False,
                        "supported_datasets": [task["dataset"] for task in inputs["tasks"]],
                        "node_id": "postgres-fixture-node",
                        "network_available": 16,
                        "cpu_cores": 16,
                        "mem_mb": 65536,
                        "disk_gb": 100,
                    },
                )

            monkeypatch.setattr("autoeval.evaluation.submission.resolve_inputs", resolve)
            monkeypatch.setattr("autoeval.evaluation.submission.current_preflight", preflight)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as c:
                body = submission()
                body.update(target_id=target_id, resource_id=resource_id)

                async def send(key, value):
                    return await c.post(
                        "/api/autoeval/v1/evaluation-tasks",
                        json=value,
                        headers={"Idempotency-Key": key},
                    )

                a, b = await asyncio.gather(send("same-intent", body), send("same-intent", body))
                assert a.status_code == b.status_code == 202, (a.text, b.text)
                rid = a.json()["data"]["run_id"]
                assert b.json()["data"]["run_id"] == rid
                changed = copy.deepcopy(body)
                changed["tasks"][0]["concurrency"] = 3
                assert (await send("same-intent", changed)).status_code == 409
                single = submission(("GPQA",))
                single.update(target_id=target_id, resource_id=resource_id)
                assert (await send("single", single)).status_code == 202
                async with app.state.sessions() as session:
                    assert (
                        await session.scalar(select(func.count()).select_from(EvaluationRun)) == 2
                    )
                    assert await session.scalar(select(func.count()).select_from(Outbox)) == 2
                    assert await session.scalar(select(func.count()).select_from(PlanningJob)) == 0
                    frozen = await session.scalar(
                        select(RunSnapshot).where(RunSnapshot.run_id == uuid.UUID(rid))
                    )
                    assert frozen.canonical_body["inputs"]["tasks"][0]["concurrency"] == 2
                    assert frozen.canonical_body["estimate"] is None
                detail = (await c.get(f"/api/autoeval/v1/evaluation-tasks/{rid}")).json()["data"]
                assert len(detail["datasets"]) == 2
                first = (await c.get("/api/autoeval/v1/evaluation-tasks?limit=1")).json()
                assert first["statistics"]["total"] == 2 and first["next_offset"] == 1
                second = (await c.get("/api/autoeval/v1/evaluation-tasks?limit=1&offset=1")).json()
                assert first["data"][0]["id"] != second["data"][0]["id"]
                assert (await c.get("/api/autoeval/v1/evaluation-tasks?state=completed")).json()[
                    "statistics"
                ]["total"] == 0
                async with app.state.sessions() as session, session.begin():
                    children = (
                        await session.scalars(
                            select(DatasetExecution).where(
                                DatasetExecution.run_id == uuid.UUID(rid)
                            )
                        )
                    ).all()
                    for index, child in enumerate(children):
                        session.add(
                            DatasetExecutionEnvironment(
                                dataset_execution_id=child.id,
                                resource_id=uuid.UUID(resource_id),
                                template=template,
                                container_id=str(index + 1) * 64,
                                state="cleanup_pending",
                            )
                        )
                    children[0].state = "succeeded"
                    children[1].state = "failed"
                    children[1].summary = {"reason": "TEST-partial-failure"}
                assert (
                    await c.post(f"/api/autoeval/v1/evaluation-tasks/{rid}/cancel")
                ).status_code == 202
                async with app.state.sessions() as session:
                    assert (await session.get(EvaluationRun, uuid.UUID(rid))).cancel_requested_at
                detail = (await c.get(f"/api/autoeval/v1/evaluation-tasks/{rid}")).json()["data"]
                environments = [row["execution_environment"] for row in detail["datasets"]]
                assert {row["resource_id"] for row in environments} == {resource_id}
                assert {row["container_id"] for row in environments} == {"1" * 12, "2" * 12}
                assert {row["state"] for row in environments} == {"cleanup_pending"}
                # Historical tasks normalize to one dataset without rewriting snapshots.
                async with app.state.sessions() as session, session.begin():
                    legacy = EvaluationRun(
                        trigger_scope="local-operator:evaluation",
                        idempotency_key="old",
                        request_hash="c" * 64,
                        run_mode="exploration",
                        created_by="operator",
                    )
                    session.add(legacy)
                    await session.flush()
                    legacy_id = legacy.id
                    session.add(
                        RunSnapshot(
                            run_id=legacy.id,
                            schema_version="legacy.v1",
                            sha256="c" * 64,
                            canonical_body={
                                "execution_origin": "real",
                                "remote_model": "TEST-hidden",
                            },
                        )
                    )
                assert (await c.get("/api/autoeval/v1/evaluation-tasks")).json()["statistics"][
                    "total"
                ] == 2
                assert (await c.get("/api/autoeval/v1/evaluation-tasks?include_test=true")).json()[
                    "statistics"
                ]["total"] == 3
                old = (await c.get(f"/api/autoeval/v1/evaluation-tasks/{legacy_id}")).json()["data"]
                assert len(old["datasets"]) == 1

                # Separate paid-probe scope: different submission keys must still not duplicate
                # the same active or unresolved model/resource operation.
                async def ready(*args):
                    return True

                async def no_object_write(*args, **kwargs):
                    return None

                monkeypatch.setattr("autoeval.planning.probe_dispatch.consumer_ready", ready)
                monkeypatch.setattr("autoeval.planning.routes.artifact", no_object_write)
                probe_body = {
                    "target_id": target_id,
                    "resource_id": body["resource_id"],
                    "resource_kind": "customer_ssh",
                    "concurrency": [1],
                }

                async def probe(key):
                    return await c.post(
                        "/api/autoeval/v1/planning/probes",
                        json=probe_body,
                        headers={"Idempotency-Key": key},
                    )

                responses = await asyncio.gather(probe("probe-a"), probe("probe-b"))
                assert sorted(r.status_code for r in responses) == [202, 409]
                saved = next(r for r in responses if r.status_code == 202).json()["data"]
                async with app.state.sessions() as session, session.begin():
                    original_probe = await session.get(PlanningJob, uuid.UUID(saved["id"]))
                    original_probe.state = "unresolved"
                active = (
                    await c.get(
                        "/api/autoeval/v1/planning/active-probe",
                        params={
                            "target_id": target_id,
                            "resource_id": body["resource_id"],
                            "resource_kind": "customer_ssh",
                        },
                    )
                ).json()["data"]
                assert active["id"] == saved["id"] and active["state"] == "unresolved"
                assert (await probe("probe-c")).status_code == 409
                async with app.state.sessions() as session:
                    assert await session.scalar(select(func.count()).select_from(PlanningJob)) == 1
                probe_body["resource_id"] = str(uuid.uuid4())
                queued = (await probe("probe-other-resource")).json()["data"]
                assert (
                    await c.post(f"/api/autoeval/v1/planning/probes/{queued['id']}/cancel")
                ).status_code == 202
                assert (await c.get(f"/api/autoeval/v1/planning/probes/{queued['id']}")).json()[
                    "data"
                ]["state"] == "cancelled"
                # Expired preflight is refreshed without issuing a generating request.
                from autoeval.planning.planning_worker import ProbePreflightBlocked, execute_job

                class ProbeAdapter:
                    checks = 0
                    submits = 0

                    async def preflight(self):
                        self.checks += 1
                        return {"planner_ready": False}

                    async def submit(self, *args):
                        self.submits += 1
                        raise AssertionError("No model calls during validation")

                adapter = ProbeAdapter()

                async def transport(*args):
                    return adapter

                async def expired(*args, **kwargs):
                    return None

                monkeypatch.setattr("autoeval.planning.planning_worker.transport", transport)
                monkeypatch.setattr("autoeval.planning.planning_worker.current_preflight", expired)
                async with app.state.sessions() as session, session.begin():
                    candidate = PlanningJob(
                        kind="probe",
                        state="pending",
                        payload={
                            **probe_body,
                            "requests_per_level": 2,
                            "prompt_tokens": 512,
                            "max_tokens": 512,
                        },
                    )
                    session.add(candidate)
                    await session.flush()
                    probe_id = candidate.id
                with pytest.raises(ProbePreflightBlocked, match="未提交模型请求"):
                    await execute_job(app.state.sessions, settings, probe_id)
                assert adapter.checks == 1 and adapter.submits == 0

                # Read-only remote reconciliation and explicit audited closure.
                async def status(job):
                    return SimpleNamespace(state="unknown")

                adapter.status = status
                monkeypatch.setattr("autoeval.planning.planning_transport.transport", transport)
                path = "/api/autoeval/v1/planning/probes/" + saved["id"]
                close = {
                    "reason": "TEST historical evidence unavailable",
                    "acknowledge_unknown": True,
                }
                assert (await c.post(path + "/close", json=close)).status_code == 409
                checked = await c.post(path + "/reconcile")
                assert checked.status_code == 200, checked.text
                assert checked.json()["data"]["state"] == "unresolved"
                closed = await c.post(path + "/close", json=close)
                assert closed.status_code == 200, closed.text
                assert closed.json()["data"]["result"]["closure"]["execution_outcome"] == "unknown"
                from autoeval.infrastructure.audit import AuditEvent

                async with app.state.sessions() as session:
                    event = await session.scalar(
                        select(AuditEvent).where(AuditEvent.resource_id == saved["id"])
                    )
                    assert event.details["previous_result"]["remote_check"]["state"] == "unknown"
                assert adapter.submits == 0

                from unittest.mock import AsyncMock

                from autoeval.evaluation import isolated_cleanup, orchestration
                from autoeval.evaluation.models import CapacityLease
                from autoeval.planning.planning_transport import HarborDaemonUnavailable

                harbor = submission(("DeepSWE",))
                harbor.update(target_id=target_id, resource_id=resource_id)
                accepted = await send("r13-harbor-start-failure", harbor)
                assert accepted.status_code == 202, accepted.text
                harbor_id = uuid.UUID(accepted.json()["data"]["run_id"])
                container_id = "d" * 64
                remote = SimpleNamespace(
                    ensure=AsyncMock(side_effect=HarborDaemonUnavailable(container_id)),
                    submit=AsyncMock(),
                    remove=AsyncMock(return_value=True),
                )
                execution_transport = AsyncMock(return_value=remote)
                cleanup_transport = AsyncMock(return_value=remote)
                monkeypatch.setattr(orchestration, "isolated_transport", execution_transport)
                monkeypatch.setattr(isolated_cleanup, "isolated_transport", cleanup_transport)
                monkeypatch.setattr(
                    orchestration, "execution_template", lambda *a: {**template, "family": "harbor"}
                )
                monkeypatch.setattr(orchestration.FileSecretStore, "get", lambda *a: "test-only")
                monkeypatch.setattr(
                    "autoeval.billing.transport.execution_route", lambda *a, **kw: None
                )
                monkeypatch.setattr(orchestration, "write_manifest", lambda *a: None)
                monkeypatch.setattr(
                    "autoeval.reporting.task_reports.publish_task_report", AsyncMock()
                )
                async with asyncio.timeout(10):
                    await orchestration.execute(app.state.sessions, settings, harbor_id)
                remote.ensure.assert_awaited_once()
                remote.submit.assert_not_awaited()
                remote.remove.assert_awaited_once()
                assert cleanup_transport.await_args.kwargs["container_id"] == container_id

                async with app.state.sessions() as session:
                    run = await session.get(EvaluationRun, harbor_id)
                    child = await session.scalar(
                        select(DatasetExecution).where(DatasetExecution.run_id == harbor_id)
                    )
                    environment = await session.get(DatasetExecutionEnvironment, child.id)
                    lease = await session.scalar(
                        select(CapacityLease).where(CapacityLease.owner_id == child.id)
                    )
                    assert run.state == child.state == "failed"
                    assert environment.state == "cleaned" and lease.released

                import json
                from pathlib import Path

                from autoeval.reporting.models import CaseExecutionRecord, UnifiedCollection

                accepted = await send("r13-harbor-archive-retry", harbor)
                assert accepted.status_code == 202
                retry_id = uuid.UUID(accepted.json()["data"]["run_id"])
                fixture_path = Path(__file__).parent / "fixtures/unified_outputs/deepswe.json"
                unified = json.loads(fixture_path.read_bytes())
                case = next(case for case in unified["cases"] if case["status"] == "success")
                unified["cases"] = [{**case, "case_id": "0", "dataset": "DeepSWE"}]
                unified["case_count"] = 1
                remote.ensure.reset_mock(side_effect=True, return_value=True)
                remote.ensure.return_value = container_id
                remote.status = AsyncMock(return_value=SimpleNamespace(state="succeeded"))
                remote.collect = AsyncMock(
                    return_value={"result": {"unified_result": unified, "tool_exit_code": 0}}
                )
                remote.remove.reset_mock()

                objects = {}
                failed_writes = []

                def put_object(settings, key, raw):
                    if key.startswith("unified-results/") and not failed_writes:
                        failed_writes.append(key)
                        raise OSError("Injected object store outage")
                    objects[key] = raw

                async def report_terminal_lease(*args):
                    async with app.state.sessions() as session:
                        child = await session.scalar(
                            select(DatasetExecution).where(DatasetExecution.run_id == retry_id)
                        )
                        lease = await session.scalar(
                            select(CapacityLease).where(CapacityLease.owner_id == child.id)
                        )
                        if failed_writes and remote.collect.await_count == 2:
                            assert child.summary["archive_pending"] is True
                            assert not lease.released
                            remote.remove.assert_not_awaited()
                    return {"result": {"unified_result": unified, "tool_exit_code": 0}}

                remote.collect.side_effect = report_terminal_lease
                for module in (
                    "autoeval.planning.artifacts",
                    "autoeval.reporting.unified_outputs",
                    "autoeval.reporting.langfuse_integration",
                ):
                    monkeypatch.setattr(module + ".write_manifest", put_object)
                # Simulate Worker loss after the daemon accepted the first submission.
                remote.submit.side_effect = asyncio.CancelledError
                with pytest.raises(asyncio.CancelledError):
                    await orchestration.execute(app.state.sessions, settings, retry_id)
                async with app.state.sessions() as session:
                    saved_child = await session.scalar(
                        select(DatasetExecution).where(DatasetExecution.run_id == retry_id)
                    )
                    saved_environment = await session.get(
                        DatasetExecutionEnvironment, saved_child.id
                    )
                    assert saved_child.state == saved_environment.state == "submitting"
                    assert saved_environment.container_id == container_id
                remote.remove.assert_not_awaited()
                remote.submit.side_effect = None

                async with asyncio.timeout(15):
                    await orchestration.execute(app.state.sessions, settings, retry_id)

                remote.submit.assert_awaited_once()
                remote.ensure.assert_awaited_once()
                assert execution_transport.await_args.kwargs["container_id"] == container_id
                assert all(
                    call.args[0].submission_key == str(saved_child.id)
                    for call in remote.status.await_args_list
                )
                remote.remove.assert_awaited_once()
                assert remote.collect.await_count == 2 and len(failed_writes) == 1
                async with app.state.sessions() as session:
                    run = await session.get(EvaluationRun, retry_id)
                    evidence = await session.scalar(
                        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == retry_id)
                    )
                    collection = await session.scalar(
                        select(UnifiedCollection).where(UnifiedCollection.run_id == retry_id)
                    )
                    assert run.state == "completed"
                    assert evidence.sample_id == "0" and evidence.object_key in objects
                    assert collection.object_key in objects

                accepted = await send("r13-cancel-during-container-start", harbor)
                assert accepted.status_code == 202
                cancelled_id = uuid.UUID(accepted.json()["data"]["run_id"])
                remote.submit.reset_mock()
                remote.status.reset_mock()
                remote.remove.reset_mock()

                async def cancel_during_start():
                    response = await c.post(
                        f"/api/autoeval/v1/evaluation-tasks/{cancelled_id}/cancel"
                    )
                    assert response.status_code == 202
                    assert response.json()["data"]["accepted"] is True
                    return container_id

                remote.ensure.side_effect = cancel_during_start
                async with asyncio.timeout(10):
                    await orchestration.execute(app.state.sessions, settings, cancelled_id)
                remote.submit.assert_not_awaited()
                remote.status.assert_not_awaited()
                remote.remove.assert_awaited_once()

                async with app.state.sessions() as session:
                    run = await session.get(EvaluationRun, cancelled_id)
                    child = await session.scalar(
                        select(DatasetExecution).where(DatasetExecution.run_id == cancelled_id)
                    )
                    environment = await session.get(DatasetExecutionEnvironment, child.id)
                    lease = await session.scalar(
                        select(CapacityLease).where(CapacityLease.owner_id == child.id)
                    )
                    assert run.state == child.state == "cancelled"
                    assert environment.container_id == container_id
                    assert environment.state == "cleaned" and lease.released

                mixed = submission(("AutomationBench", "DeepSWE"))
                mixed.update(target_id=target_id, resource_id=resource_id)
                accepted = await send("r13-shared-node-isolation", mixed)
                assert accepted.status_code == 202
                mixed_id = uuid.UUID(accepted.json()["data"]["run_id"])
                async with app.state.sessions() as session:
                    children = await session.scalars(
                        select(DatasetExecution).where(DatasetExecution.run_id == mixed_id)
                    )
                    owners = {child.payload["dataset"]: child.id for child in children}

                async def remove_failed_child():
                    async with app.state.sessions() as session:
                        survivor = await session.get(DatasetExecutionEnvironment, owners["DeepSWE"])
                        reserved = await session.scalar(
                            select(CapacityLease).where(CapacityLease.owner_id == owners["DeepSWE"])
                        )
                        assert survivor.container_id == "2" * 64
                        assert not reserved.released
                    return True

                failed_adapter = SimpleNamespace(
                    ensure=AsyncMock(return_value="1" * 64),
                    submit=AsyncMock(),
                    status=AsyncMock(return_value=SimpleNamespace(state="failed")),
                    remove=AsyncMock(side_effect=remove_failed_child),
                )
                successful_adapter = SimpleNamespace(
                    ensure=AsyncMock(return_value="2" * 64),
                    submit=AsyncMock(),
                    status=AsyncMock(return_value=SimpleNamespace(state="succeeded")),
                    collect=AsyncMock(
                        return_value={"result": {"unified_result": unified, "tool_exit_code": 0}}
                    ),
                    remove=AsyncMock(return_value=True),
                )

                async def choose_adapter(session, settings, resource, owner, template, **kwargs):
                    assert resource == resource_id or resource == uuid.UUID(resource_id)
                    return (
                        failed_adapter if owner == owners["AutomationBench"] else successful_adapter
                    )

                monkeypatch.setattr(orchestration, "isolated_transport", choose_adapter)
                monkeypatch.setattr(isolated_cleanup, "isolated_transport", choose_adapter)
                async with asyncio.timeout(10):
                    await orchestration.execute(app.state.sessions, settings, mixed_id)
                failed_adapter.submit.assert_awaited_once()
                successful_adapter.submit.assert_awaited_once()
                failed_adapter.remove.assert_awaited_once()
                successful_adapter.remove.assert_awaited_once()
                async with app.state.sessions() as session:
                    evidence = await session.scalar(
                        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == mixed_id)
                    )
                    assert evidence.dataset_key == "DeepSWE"
                    assert (
                        await session.get(DatasetExecution, owners["AutomationBench"])
                    ).state == "failed"
                    assert (
                        await session.get(DatasetExecution, owners["DeepSWE"])
                    ).state == "succeeded"
                    for owner in owners.values():
                        environment = await session.get(DatasetExecutionEnvironment, owner)
                        lease = await session.scalar(
                            select(CapacityLease).where(CapacityLease.owner_id == owner)
                        )
                        assert environment.state == "cleaned" and lease.released
    finally:
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()
