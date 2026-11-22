import copy
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from autoeval.catalog.datasets import canonical_manifest
from autoeval.reporting import task_reports as tr
from autoeval.reporting.report_integrity import report_evidence_status


def inputs():
    task = {
        "task_id": "AutomationBench",
        "dataset": "AutomationBench",
        "samples": [{"sample_id": "a", "tool_case_id": "a"}],
        "compilation": {"config": {"subcommand": "harbor_agent", "params": {}}},
        "manifest_id": "m",
        "manifest_sha256": "a" * 64,
        "compilation_id": "c",
        "tool": {"revision": "pinned"},
        "subset_scope": "full",
        "concurrency": 12,
        "dataset_samples": 1,
    }
    case = {
        "case_id": "automationbench/a",
        "attempt": 1,
        "trial_name": "t",
        "trial_dir": "t",
        "status": "success",
        "score": None,
        "finished_at": "2026-11-18T00:00:00Z",
        "input_tokens": 0,
        "output_tokens": 0,
    }
    original = {
        "schema_version": 1,
        "tool": "ais_bench",
        "subcommand": "harbor_agent",
        "case_count": 1,
        "cases": [case],
    }
    native = {
        "t": {
            "result.json": json.dumps(
                {
                    "task_name": "automationbench/a",
                    "trial_name": "t",
                    "finished_at": case["finished_at"],
                    "verifier_result": {"rewards": {"accuracy": 1}},
                    "exception_info": None,
                }
            ),
            "verifier/reward.json": '{"accuracy":1}',
        }
    }
    return task, original, native


def test_follow_up_requires_all_frozen_attempts():
    task, original, native = inputs()
    task["attempts"] = 2
    recovered, _ = tr.restore_native_scores(original, task, native)
    partial = tr.scored_summary(canonical_manifest(recovered), task, require_attempt_group=True)
    assert partial["validity"] == "partial"
    assert partial["incomplete_attempt_groups"] == 1
    assert partial["accuracy"] is None
    recovered["cases"].append({**recovered["cases"][0], "attempt": 2, "score": 0})
    recovered["case_count"] = 2
    complete = tr.scored_summary(canonical_manifest(recovered), task, require_attempt_group=True)
    assert complete["validity"] == "complete"
    assert complete["accuracy"] == 50
    assert complete["metric_conversion"] == "verified_harbor_trial_accuracy"


def test_native_recovery_preserves_history_and_unknown_tokens():
    task, original, native = inputs()
    saved = copy.deepcopy(original)
    recovered, hashes = tr.restore_native_scores(original, task, native)
    assert original == saved and len(hashes) == 2
    assert recovered["cases"][0]["score"] == 1 and recovered["cases"][0]["input_tokens"] is None
    assert tr.scored_summary(canonical_manifest(recovered), task)["accuracy"] == 100
    frozen = {"remote_model": "model", "inputs": {"tasks": [task, {"dataset": "GPQA"}]}}
    saved = copy.deepcopy(frozen)
    context = tr.dataset_context(frozen, task)
    assert len(context["inputs"]["tasks"]) == 1 and frozen == saved


@pytest.mark.parametrize(
    "problem", ["missing", "extra", "task", "trial", "time", "reward", "exception"]
)
def test_native_recovery_rejects_invalid_sources(problem):
    task, original, native = inputs()
    if problem == "missing":
        native.clear()
    elif problem == "extra":
        native["extra"] = native["t"]
    elif problem == "reward":
        native["t"]["verifier/reward.json"] = '{"accuracy":0}'
    else:
        r = json.loads(native["t"]["result.json"])
        r[
            {
                "task": "task_name",
                "trial": "trial_name",
                "time": "finished_at",
                "exception": "exception_info",
            }[problem]
        ] = "invalid"
        native["t"]["result.json"] = json.dumps(r)
    with pytest.raises(ValueError):
        tr.restore_native_scores(original, task, native)


async def test_one_report_multiple_datasets_idempotent_and_integrity(monkeypatch):
    task, original, native = inputs()
    abody, _ = tr.restore_native_scores(original, task, native)
    gpqa = {
        **task,
        "task_id": "GPQA",
        "dataset": "GPQA",
        "samples": [{"sample_id": "gpqa_diamond:0", "tool_case_id": "0"}],
        "compilation": {"config": {"subcommand": "llm_accuracy", "params": {}}},
    }
    gbody = copy.deepcopy(abody)
    gbody["subcommand"] = "llm_accuracy"
    gbody["cases"][0].update(dataset="GPQA", case_id="gpqa_diamond:0", score=0)
    run = SimpleNamespace(id=uuid.uuid4(), state="failed")
    frozen = {
        "remote_model": "model",
        "execution_origin": "real",
        "inputs": {"tasks": [task, gpqa]},
    }
    snap = SimpleNamespace(canonical_body=frozen, sha256=tr.checksum(frozen))
    a = SimpleNamespace(id=uuid.uuid4(), object_key="a", sha256=tr.checksum(abody))
    g = SimpleNamespace(id=uuid.uuid4(), object_key="g", sha256=tr.checksum(gbody))
    objects = {"a": abody, "g": gbody}
    added = []
    reader = lambda settings, row: objects[row.object_key]
    monkeypatch.setattr(tr, "read_manifest", reader)
    monkeypatch.setattr(
        tr, "write_manifest", lambda settings, key, raw: objects.__setitem__(key, json.loads(raw))
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=run),
        scalar=AsyncMock(side_effect=[snap, a, g, None]),
        add=added.append,
        flush=AsyncMock(),
    )
    report = await tr.publish_task_report(session, None, run.id)
    body = objects[report.object_key]
    assert len(added) == 1 and body["summary"]["accuracy"] is None
    assert [d["summary"]["accuracy"] for d in body["datasets"]] == [100, 0]
    assert run.state == "failed"
    session.scalar = AsyncMock(side_effect=[snap, a, g, report])
    assert await tr.publish_task_report(session, None, run.id) is report
    monkeypatch.setattr("autoeval.reporting.report_integrity.read_manifest", reader)
    assert await report_evidence_status(None, report, run, snap) == "verified"
    objects["a"]["cases"][0]["score"] = 0
    assert await report_evidence_status(None, report, run, snap) == "invalid"


async def test_postgres_append_only_recovery(monkeypatch):
    import os

    if not os.environ.get("AE_REPORT_RECOVERY_PG"):
        pytest.skip("Set AE_REPORT_RECOVERY_PG for a disposable PostgreSQL transaction")
    from sqlalchemy import func, select

    from autoeval.evaluation.models import EvaluationReport, ResultArchiveRevision
    from autoeval.infrastructure.config import get_settings
    from autoeval.infrastructure.db import create_database
    from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
    from autoeval.reporting.models import UnifiedCollection

    task, original, native = inputs()
    # The frozen original collection already uses platform sample identities.
    parent_body = copy.deepcopy(original)
    parent_body["cases"][0].update(case_id="a", dataset="AutomationBench")
    recovered, hashes = tr.restore_native_scores(original, task, native)
    objects = {"parent": parent_body}
    monkeypatch.setattr(tr, "read_manifest", lambda settings, row: objects[row.object_key])
    monkeypatch.setattr(
        tr, "write_manifest", lambda settings, key, raw: objects.__setitem__(key, json.loads(raw))
    )
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as db:
            await db.begin()
            try:
                run = EvaluationRun(
                    trigger_scope="local-operator:unified-fixture",
                    idempotency_key=str(uuid.uuid4()),
                    request_hash="a" * 64,
                    run_mode="exploration",
                    created_by="test",
                    state="failed",
                )
                db.add(run)
                await db.flush()
                frozen = {
                    "remote_model": "TEST-no-model",
                    "execution_origin": "simulation",
                    "inputs": {"tasks": [task]},
                }
                db.add(
                    RunSnapshot(
                        run_id=run.id,
                        schema_version="planned-run.v1",
                        canonical_body=frozen,
                        sha256=tr.checksum(frozen),
                    )
                )
                parent = UnifiedCollection(
                    run_id=run.id,
                    collection_key="AutomationBench",
                    object_key="parent",
                    sha256=tr.checksum(parent_body),
                    payload={
                        "expected": {"AutomationBench": ["a"]},
                        "summary": {"validity": "partial"},
                    },
                )
                db.add(parent)
                await db.flush()
                parent_payload = copy.deepcopy(parent.payload)
                row = await tr.archive_revision(
                    db,
                    None,
                    run.id,
                    "AutomationBench",
                    canonical_manifest(recovered),
                    reason="test recovery",
                    source_hashes=hashes,
                )
                again = await tr.archive_revision(
                    db,
                    None,
                    run.id,
                    "AutomationBench",
                    canonical_manifest(recovered),
                    reason="test recovery",
                    source_hashes=hashes,
                )
                assert row.id == again.id
                report = await tr.publish_task_report(db, None, run.id, revision_ids=[row.id])
                assert (
                    await tr.publish_task_report(db, None, run.id, revision_ids=[row.id])
                ).id == report.id
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ResultArchiveRevision)
                        .where(ResultArchiveRevision.run_id == run.id)
                    )
                    == 1
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(EvaluationReport)
                        .where(EvaluationReport.run_id == run.id)
                    )
                    == 1
                )
                assert run.state == "failed" and parent.payload == parent_payload
                from autoeval.evaluation.models import DatasetExecution
                from autoeval.infrastructure.models import RunEvent

                child = DatasetExecution(
                    run_id=run.id,
                    task_id="AutomationBench",
                    payload=task,
                    state="failed",
                    summary={"validity": "partial"},
                )
                db.add(child)
                await db.flush()
                monkeypatch.setattr(
                    "autoeval.reporting.report_integrity.read_manifest",
                    lambda settings, row: objects[row.object_key],
                )
                await tr.apply_recovered_state(db, None, report)
                await db.flush()
                assert run.state == "completed" and child.state == "succeeded"
                await tr.apply_recovered_state(db, None, report)
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(RunEvent)
                        .where(RunEvent.run_id == run.id, RunEvent.type == "results_recovered")
                    )
                    == 1
                )
                assert parent.payload == parent_payload
                assert (
                    await tr.publish_task_report(db, None, run.id, revision_ids=[row.id])
                ).id == report.id

                # A second interpretation must not overwrite a published task report.
                with pytest.raises(ValueError, match="immutable report"):
                    await tr.publish_task_report(db, None, run.id)
            finally:
                await db.rollback()
    finally:
        await engine.dispose()


def test_after_execution_reference_is_pinned_and_never_a_release_verdict():
    import hashlib

    from autoeval.catalog.benchmarks import compare_baseline

    task, _, _ = inputs()
    frozen = {"remote_model": "model", "inputs": {"tasks": [task]}}
    context = tr.dataset_context(frozen, task)
    raw = json.dumps(
        {"metric": "pass_rate", "median": 60.5, "unit": "percent", "range": [59.5, 61.5]}
    )
    source = {
        "benchmark": "AutomationBench",
        "revision": "fixed-version",
        "repository": "SJTUyh/AutoEval-Standard",
        "source_model": "model",
        "file": {
            "path": "model/AutomationBench/baseline.json",
            "raw": raw,
            "sha256": hashlib.sha256(raw.encode()).hexdigest(),
        },
    }
    row = SimpleNamespace(
        id=uuid.uuid4(),
        value=60.5,
        dataset_key="AutomationBench",
        metric_name="accuracy",
        conditions={
            "reference_only": True,
            "context_sha256": tr.checksum(context),
            "standard_baseline_source": source,
        },
    )
    summary = {
        "accuracy": 58.1667,
        "validity": "complete",
        "scoring_status": "succeeded",
        "subset_scope": "full",
    }
    comparison = compare_baseline(summary, context, [row])
    assert comparison["status"] == "matched" and comparison["verdict"] is None
    assert comparison["attached_after_execution"] is True
    assert comparison["comparison_kind"] == "standard_reference"
    assert comparison["difference"] == pytest.approx(-2.3333)
    source["file"]["raw"] = "tampered"
    with pytest.raises(ValueError, match="hash mismatch"):
        compare_baseline(summary, context, [row])
