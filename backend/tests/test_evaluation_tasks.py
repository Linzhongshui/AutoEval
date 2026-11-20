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
from autoeval.evaluation.models import DatasetExecution
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.models import Base, EvaluationRun, Outbox, RunSnapshot
from autoeval.planning import PlanningJob
from autoeval.planning.planning_transport import PlanningRemoteContainer
from autoeval.resources.models import TargetBinding


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

            async def resolve(session, settings, body):
                inputs = body.model_dump(mode="json")
                for t in inputs["tasks"]:
                    t.update(
                        concurrency=t.get("concurrency") or 1,
                        samples=[{"sample_id": "0"}],
                        manifest_sha256="a" * 64,
                        tool={},
                        subset_scope="lite",
                        compilation={
                            "config": {"params": {"batch_size": t.get("concurrency") or 1}}
                        },
                    )
                return inputs

            async def preflight(*args, **kwargs):
                return SimpleNamespace(
                    sha256="b" * 64,
                    payload={
                        "execution_ready": True,
                        "planner_ready": False,
                        "supported_datasets": ["GPQA", "MMMU-Pro"],
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
                body["target_id"] = target_id

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
                single["target_id"] = target_id
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
                    children[0].state = "succeeded"
                    children[1].state = "failed"
                    children[1].summary = {"reason": "TEST-partial-failure"}
                assert (
                    await c.post(f"/api/autoeval/v1/evaluation-tasks/{rid}/cancel")
                ).status_code == 202
                async with app.state.sessions() as session:
                    assert (await session.get(EvaluationRun, uuid.UUID(rid))).cancel_requested_at
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
    finally:
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()
