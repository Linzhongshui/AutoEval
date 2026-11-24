import hashlib
import json
import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from autoeval.billing.transport import route_compilation
from autoeval.evaluation.performance import performance_inputs
from autoeval.planning.schemas import AgentXPerformance, PerformanceTask
from autoeval.reporting import performance
from autoeval.reporting.report_view import report_task_type
from autoeval_runtime import performance_adapter as adapter
from autoeval_runtime.planning_runtime import validate_spec

HISTORICAL_TYPES = [
    ({"inputs": {"tasks": [{"compilation": {"config": None}, "dataset": "GPQA"}]}}, "accuracy"),
    ({"inputs": {"tasks": [{"compilation": {"config": None}}]}}, "other"),
    ({"inputs": {"tasks": [{"compilation": [], "dataset": {}}]}}, "other"),
    ({"task_type": []}, "other"),
    ({"inputs": {"tasks": [{"compilation": {"config": {"subcommand": "agentx"}}}]}}, "performance"),
]


@pytest.mark.parametrize("snapshot,expected", HISTORICAL_TYPES)
def test_historical_report_type(snapshot, expected):
    assert report_task_type(snapshot) == expected


@pytest.mark.parametrize("duration,limit", [(899, None), (900, 1)])
def test_benchmark_rejects_short_or_limited_trace(duration, limit):
    with pytest.raises(ValidationError):
        AgentXPerformance(
            kind="agentx",
            run_mode="benchmark",
            variant="256k",
            concurrency=1,
            duration=duration,
            trace_limit=limit,
        )


def test_performance_template_and_gateway(tmp_path):
    node, target = map(str, (uuid.uuid4(), uuid.uuid4()))
    spec = PerformanceTask(
        resource_kind="customer_ssh",
        resource_id=node,
        target_id=target,
        performance={"kind": "agentx", "variant": "256k", "duration": 60, "concurrency": 1},
    )
    settings = SimpleNamespace(planning_container_config=tmp_path / "nodes.json")
    binding = {"tokenizer_path": "/models/demo", "context_tokens": 262144}
    entry = {
        "image_id": "sha256:" + "a" * 64,
        "revision": adapter.REVISION,
        "targets": {target: binding},
    }
    settings.planning_container_config.write_text(
        json.dumps({node: {"executors": {"agentx": entry}}})
    )
    remote = {"model": "test-model", "base_url": "https://test.invalid/v1"}
    frozen = performance_inputs(settings, spec, remote)
    (child,) = frozen["tasks"]
    compiled = route_compilation(child["compilation"], {"base_url": "http://10.0.0.1/runs/abc/v1"})
    assert child["compilation"]["config"]["params"]["url"] == remote["base_url"]
    params = compiled["config"]["params"]
    argv = adapter.arguments(params, tmp_path, dry_run=True)
    assert argv[argv.index("--url") + 1] == "http://10.0.0.1/runs/abc"
    assert argv[-1] == "--dry-run" and "secret" not in argv
    levels = adapter.arguments({**params, "concurrency": [1, 4]}, tmp_path)
    start = levels.index("--batch-size") + 1
    assert levels[start : start + 2] == ["1", "4"]
    validate_spec(
        {"kind": "adaptor", "compilation": compiled, "tool": child["tool"], "credential": "fixture"}
    )
    binding["context_tokens"] = 32768
    settings.planning_container_config.write_text(
        json.dumps({node: {"executors": {"agentx": entry}}})
    )
    with pytest.raises(HTTPException, match="上下文"):
        performance_inputs(settings, spec, remote)


class MemoryStore:
    def __init__(self):
        self.objects = {}
        self.metadata = {}

    def close(self):
        pass

    def upload_fileobj(self, stream, bucket, key, ExtraArgs):
        self.objects[key] = stream.read()
        self.metadata[key] = ExtraArgs["Metadata"]

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.objects[Key]), "Metadata": self.metadata[Key]}

    def get_object(self, Bucket, Key):
        return {
            "Body": SimpleNamespace(
                iter_chunks=lambda **kw: iter([self.objects[Key]]), close=lambda: None
            )
        }


@pytest.mark.asyncio
async def test_native_outputs_archive_csv_and_preserve_early_eos(tmp_path, monkeypatch):
    root = tmp_path / "performances/autoeval"
    root.mkdir(parents=True)
    raw = (
        b"Performance Parameters,Stage,Average,P90\r\nOutputTokens,total,7,8\r\n"
        b"InputTokens,total,35,35\r\nTTFT,total,401.25 ms,483.5 ms\r\n"
    )
    (root / "synthetic.csv").write_bytes(raw)
    (root / "synthetic.json").write_text(
        json.dumps(
            {
                "Success Requests": {"total": 2},
                "Total Requests": {"total": 2},
                "Request Throughput": {"total": "1.25 req/s"},
                "Total Generated Tokens": {"total": 14},
            }
        )
    )
    params = {
        "kind": "inference",
        "input_tokens": 32,
        "max_output_tokens": 16,
        "requests": 2,
        "concurrency": 1,
        "url": "https://test.invalid/v1",
        "model": "fixture",
        "tokenizer_path": "/models/test",
    }
    cmd = adapter.arguments(params, tmp_path)
    assert "perf" in cmd and "--num-warmups" in cmd
    assert "ignore_eos=True" not in (tmp_path / "inference.py").read_text()

    async def result(job, kind):
        files = adapter.result_files(tmp_path, kind)
        return tmp_path, {"files": files, **adapter.summarize(tmp_path, kind, files)}

    transport = SimpleNamespace(
        performance_result=result,
        copy_performance_file=lambda output, path, dest: dest.write((output / path).read_bytes()),
    )
    child = SimpleNamespace(
        id=uuid.uuid4(), payload={"compilation": {"config": {"params": params}}}
    )
    store = MemoryStore()
    monkeypatch.setattr(performance, "storage", lambda settings: store)
    settings = SimpleNamespace(s3_bucket="test")
    state, summary = await performance.archive_performance(
        settings,
        transport,
        "job",
        child,
        uuid.uuid4(),
        {"tool_exit_code": 0},
        "succeeded",
        ("fixture-secret",),
    )
    assert state == "succeeded" and summary["validity"] == "complete"
    data = summary["performance"]
    assert ["OutputTokens", "total / Average", 7, "token"] in data["metrics"]
    assert ["InputTokens", "total / Average", 35, "token"] in data["metrics"]
    assert ["TTFT", "total / P90", 483.5, "ms"] in data["metrics"]
    assert ["Request Throughput", "total", 1.25, "req/s"] in data["metrics"]
    assert performance.check_files(settings, data["files"])
    report = SimpleNamespace(summary=summary)
    with performance.verified_csv(settings, report, data["csv_path"]) as stream:
        assert stream.read() == raw
    ref = next(f for f in data["files"] if f["path"] == data["csv_path"])
    assert ref["sha256"] == hashlib.sha256(raw).hexdigest()
    store.objects[ref["object_key"]] = b"x" * len(raw)
    assert not performance.check_files(settings, data["files"], verify_summary_bytes=True)
    with pytest.raises(ValueError, match="integrity"):
        performance.verified_csv(settings, report, data["csv_path"])
    with pytest.raises(KeyError):
        performance.verified_csv(settings, report, "../other.csv")

    (root / "synthetic.csv").write_bytes(raw + b"fixture-secret")
    state, redacted = await performance.archive_performance(
        settings,
        transport,
        "job",
        child,
        uuid.uuid4(),
        {"tool_exit_code": 0},
        "succeeded",
        ("fixture-secret",),
    )
    assert state == "failed" and redacted["performance"]["parse_status"] == "restricted_evidence"
    assert all(not entry["path"].endswith(".csv") for entry in redacted["performance"]["files"])
    assert "fixture-secret" not in json.dumps(redacted)


@pytest.mark.asyncio
async def test_smoke_preserves_native_verdict_and_missing_results(tmp_path, monkeypatch):
    folder = tmp_path / "performances/agentx_256k_batchsize_1"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "result": {
                    "status": "completed",
                    "parse_status": "success",
                    "benchmark_valid": False,
                    "data_status": "complete",
                    "comparison_scope": "smoke",
                }
            }
        )
    )
    (folder / "agentx_summary.json").write_text('{"time_to_first_token":{"unit":"s","p90":0.25}}')
    (folder / "agentx_summary.csv").write_text("metric,p90\ntime_to_first_token,0.25\n")
    files = adapter.result_files(tmp_path, "agentx")
    result = adapter.summarize(tmp_path, "agentx", files)
    assert result["comparison_scope"] == "smoke" and result["benchmark_valid"] is False
    assert result["metrics"] == [["time_to_first_token", "p90", 0.25, "s"]]
    (folder / "execution_plan.redacted.json").write_text("{}")
    (folder / "agentx_raw").mkdir()
    (folder / "agentx_raw/profile_export.json").write_text("{}")
    import shutil

    shutil.copytree(folder, folder.with_name("agentx_256k_batchsize_4"))

    async def read(job, kind):
        paths = adapter.result_files(tmp_path, kind)
        return tmp_path, {"files": paths, **adapter.parse_outputs(tmp_path, kind, paths)}

    remote = SimpleNamespace(
        performance_result=read,
        copy_performance_file=lambda output, path, dest: dest.write((output / path).read_bytes()),
    )
    params = {"kind": "agentx", "concurrency": [4, 1], "run_mode": "smoke"}
    child = SimpleNamespace(
        id=uuid.uuid4(), payload={"compilation": {"config": {"params": params}}}
    )
    store = MemoryStore()
    monkeypatch.setattr(performance, "storage", lambda settings: store)

    async def collect():
        return await performance.archive_performance(
            SimpleNamespace(s3_bucket="test"),
            remote,
            "job",
            child,
            uuid.uuid4(),
            {"tool_exit_code": 0},
            "succeeded",
            (),
        )

    state, summary = await collect()
    assert state == "succeeded"
    assert [
        (l["concurrency"], l["comparison_scope"]) for l in summary["performance"]["levels"]
    ] == [(4, "smoke"), (1, "smoke")]
    params["concurrency"].append(8)
    state, summary = await collect()
    assert state == "failed" and summary["performance"]["levels"][-1]["parse_status"] == "missing"
    (folder / "agentx_summary.json").unlink()
    result = adapter.parse_outputs(tmp_path, "agentx", adapter.result_files(tmp_path, "agentx"))[
        "levels"
    ][0]
    assert result["parse_status"] == "invalid" and result["metrics"] == []
    assert report_task_type({"inputs": {"tasks": [{"dataset": "DeepSWE"}]}}) == "accuracy"
    assert report_task_type({}) == "other"
    assert report_task_type({"task_type": "performance"}) == "performance"


@pytest.mark.skipif(not os.getenv("AE_INFRA_TEST"), reason="Explicit migrated PostgreSQL required")
async def test_performance_submission_and_report_catalog_postgres(tmp_path, monkeypatch):
    import httpx
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from autoeval.catalog.registry import Asset, AssetVersion
    from autoeval.entrypoints.api import create_app
    from autoeval.evaluation import orchestration
    from autoeval.evaluation.inputs import resolve_inputs
    from autoeval.evaluation.models import DatasetExecution
    from autoeval.infrastructure.config import get_settings
    from autoeval.infrastructure.models import RunSnapshot
    from autoeval.planning.models import PlanningArtifact
    from autoeval.resources.models import TargetBinding

    node = uuid.uuid4()
    settings = get_settings().model_copy(
        update={
            "planning_container_config": str(tmp_path / "nodes.json"),
            "evaluation_origin": "real",
            "allowed_model_hosts": ["fixture.invalid"],
            "enforce_task_budget": False,
        }
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app), app.state.engine.connect() as connection:
        tx = await connection.begin()
        sessions = async_sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        app.state.sessions = sessions
        try:
            from sqlalchemy import cast, literal
            from sqlalchemy.dialects.postgresql import JSONB

            from autoeval.reporting.reports import task_type_expression

            for snapshot, expected in HISTORICAL_TYPES:
                expr = task_type_expression(cast(literal(snapshot, type_=JSONB), JSONB))
                assert await connection.scalar(select(expr)) == expected
            async with sessions() as session, session.begin():
                model = Asset(asset_key=uuid.uuid4().hex, name="test", kind="model")
                session.add(model)
                await session.flush()
                version = AssetVersion(asset_id=model.id, version="test", metadata_json={})
                session.add(version)
                await session.flush()
                target = TargetBinding(
                    model_version_id=version.id,
                    base_url="https://fixture.invalid",
                    remote_model="fixture",
                    credential_ref="0" * 32,
                )
                session.add(target)
                await session.flush()
                body = {
                    "target_id": str(target.id),
                    "resource_id": str(node),
                    "resource_kind": "customer_ssh",
                    "performance": {
                        "kind": "inference",
                        "input_tokens": 32,
                        "max_output_tokens": 16,
                        "requests": 1,
                        "concurrency": 1,
                    },
                }
                (tmp_path / "nodes.json").write_text(
                    json.dumps(
                        {
                            str(node): {
                                "executors": {
                                    "llm_perf": {
                                        "image_id": "sha256:" + "a" * 64,
                                        "revision": adapter.REVISION,
                                        "targets": {
                                            str(target.id): {
                                                "context_tokens": 65536,
                                                "tokenizer_path": "/models/test",
                                            }
                                        },
                                    }
                                }
                            }
                        }
                    )
                )
                inputs = await resolve_inputs(session, settings, PerformanceTask(**body))
                task = inputs["tasks"][0]
                payload = {
                    **inputs,
                    "supported_datasets": ["Synthetic"],
                    "cpu_cores": 4,
                    "mem_mb": 8192,
                    "disk_gb": 16,
                    "execution_ready": True,
                    "execution_templates": {task["task_id"]: task["execution_template"]},
                }
                session.add(
                    PlanningArtifact(
                        kind="resource",
                        sha256=uuid.uuid4().hex * 2,
                        object_key="unused-fixture",
                        payload=payload,
                    )
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                endpoint = "/api/autoeval/v1/evaluation-tasks"
                headers = {"Idempotency-Key": str(uuid.uuid4())}
                response = await client.post(endpoint, json=body, headers=headers)
                assert response.status_code == 202, response.text
                run = uuid.UUID(response.json()["data"]["run_id"])
                assert (await client.post(endpoint, json=body, headers=headers)).json()["data"][
                    "run_id"
                ] == str(run)
                changed = {**body, "performance": {**body["performance"], "requests": 2}}
                assert (
                    await client.post(endpoint, json=changed, headers=headers)
                ).status_code == 409
                detail = (await client.get(f"{endpoint}/{run}")).json()["data"]
                assert (
                    not detail["follow_up_enabled"]
                    and detail["datasets"][0]["dataset"] == "Synthetic"
                )
                async with sessions() as session, session.begin():
                    snap = await session.scalar(
                        select(RunSnapshot).where(RunSnapshot.run_id == run)
                    )
                    child = await session.scalar(
                        select(DatasetExecution).where(DatasetExecution.run_id == run)
                    )
                    child.state = "succeeded"
                    child.summary = {
                        "validity": "complete",
                        "performance": {
                            "parse_status": "success",
                            "metrics": [["TTFT", "P90", 3, "ms"]],
                            "files": [{"path": "synthetic.csv"}],
                        },
                    }
                objects = {}
                monkeypatch.setattr(
                    orchestration, "write_manifest", lambda _, key, raw: objects.update({key: raw})
                )
                monkeypatch.setattr(
                    "autoeval.reporting.report_integrity.read_manifest",
                    lambda _, row: json.loads(objects[row.object_key]),
                )
                monkeypatch.setattr(performance, "check_files", lambda *_: True)
                await orchestration.finish(
                    sessions, settings, run, snap.canonical_body, [child], False
                )
                for kind in ("accuracy", "performance", "other"):
                    response = await client.get(
                        "/api/autoeval/v1/reports", params={"task_type": kind}
                    )
                    assert response.status_code == 200, response.text
                    reports = [r for r in response.json()["data"] if r["run_id"] == str(run)]
                    assert bool(reports) == (kind == "performance")
                    if reports:
                        assert reports[0]["evidence_status"] == "verified"
                        assert reports[0]["summary"]["performance"]["config"] == body["performance"]
                url = "/api/autoeval/v1/reports"
                filters = {"task_type": "performance", "model": "fixture", "query": str(run)[:12]}
                first = (await client.get(url, params=filters)).json()
                assert first["total"] == 1 and first["next_offset"] is None
                state = first["data"][0]["analysis_status"]
                assert "fixture" in first["filters"]["models"]
                assert state in first["filters"]["analysis_statuses"]
                for extra in ({"analysis_status": "failed"}, {"query": "%"}, {"model": "absent"}):
                    assert (await client.get(url, params=filters | extra)).json()["total"] == 0
                empty = (await client.get(url, params=filters | {"analysis_status": state, "offset": 1})).json()
                assert empty["data"] == [] and empty["total"] == 1
        finally:
            await tx.rollback()
