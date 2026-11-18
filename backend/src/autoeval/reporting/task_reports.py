"""Append-only dataset recovery and one immutable report per evaluation task.

No function here submits tools, changes task state, or rewrites case attempts.
"""

import asyncio
import copy
import hashlib
import json
import uuid

from sqlalchemy import select

from autoeval.catalog.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.evaluation.models import DatasetExecution, EvaluationReport, ResultArchiveRevision
from autoeval.models import EvaluationRun, RunSnapshot
from autoeval.reporting.models import UnifiedCollection
from autoeval.reporting.unified_outputs import parse_output
from autoeval.result_identity import normalize_result_identities


def checksum(value):
    return hashlib.sha256(canonical_manifest(value)).hexdigest()


def dataset_context(frozen, task):
    """Dataset-specific view; the original run snapshot is never changed."""
    value = copy.deepcopy(frozen)
    params = task["compilation"]["config"]["params"]
    generation = params.get("generation_kwargs", params.get("sampling_args", {}))
    value.update(
        dataset_key=task["dataset"],
        samples=task["samples"],
        manifest_id=task["manifest_id"],
        manifest_sha256=task["manifest_sha256"],
        config_version_id=task["compilation_id"],
        tool=task["tool"],
        parameters={
            "scope": task["subset_scope"],
            "concurrency": task["concurrency"],
            "output": params.get("max_out_len", generation.get("max_tokens")),
            "temperature": generation.get("temperature"),
            "top_p": generation.get("top_p"),
        },
    )
    value["inputs"] = {**value["inputs"], "tasks": [copy.deepcopy(task)]}
    return value


def scored_summary(raw, task):
    cases, summary = parse_output(
        raw, {task["dataset"]: [s["sample_id"] for s in task["samples"]]}, task["dataset"]
    )
    latest = {}
    for case in cases:
        if (
            case["sample_id"] not in latest
            or case["attempt_no"] > latest[case["sample_id"]]["attempt_no"]
        ):
            latest[case["sample_id"]] = case
    scores = [c["score"] for c in latest.values()]
    verified = summary["validity"] == "complete" and all(
        type(v) in (int, float) and v in (0, 1) for v in scores
    )
    return {
        **summary,
        "accuracy": sum(scores) / len(scores) * 100 if verified else None,
        "scoring_status": "succeeded" if verified else "failed",
        "subset_scope": task["subset_scope"],
        "dataset_samples": task.get("dataset_samples"),
        "expected_samples": summary["expected_cases"],
        "executed_attempts": summary["attempt_count"],
        "successful_samples": summary["observed_cases"] - summary["failed_cases"],
        "failed_samples": summary["failed_cases"],
        "missing_samples": summary["missing_cases"],
        "metric_scope": "selected_manifest",
        "metric_conversion": "verified_case_accuracy" if verified else "not_verified",
    }


def restore_native_scores(original, task, native):
    """Require exact trial identity and matching native score files, not positional joins."""
    result = copy.deepcopy(original)
    seen = set()
    hashes = []
    for case in result["cases"]:
        name = case.get("trial_name") or case.get("trial_dir")
        if not name or name in seen or name not in native:
            raise ValueError("Missing or duplicate native trial identity")
        seen.add(name)
        files = native[name]
        r = json.loads(files["result.json"])
        if r.get("trial_name") != name or r.get("task_name") != case["case_id"]:
            raise ValueError("Native task/trial identity mismatch")
        if r.get("finished_at") != case.get("finished_at"):
            raise ValueError("Native attempt time mismatch")
        if r.get("exception_info"):
            raise ValueError("Native trial has execution exception")
        for path in ("result.json", "verifier/reward.json"):
            hashes.append(
                {
                    "trial": name,
                    "path": path,
                    "sha256": hashlib.sha256(files[path].encode()).hexdigest(),
                }
            )
        case["harbor_artifact"] = {
            "trial_name": name,
            "files": {k: files[k] for k in ("result.json", "verifier/reward.json")},
        }
        # Original adapter token zeros are not measurements when Harbor reports null.
        agent = r.get("agent_result") or {}
        case["input_tokens"] = agent.get("n_input_tokens")
        case["output_tokens"] = agent.get("n_output_tokens")
    if seen != set(native):
        raise ValueError("Unexpected native trials")
    result = normalize_result_identities(
        result, task["dataset"], task["compilation"]["config"], task["samples"]
    )
    return result, hashes


async def archive_revision(session, settings, run_id, dataset, raw, *, reason, source_hashes):
    """Caller supplies a transaction; serialization makes repeated import idempotent."""
    if not reason.strip() or not source_hashes:
        raise ValueError("Recovery reason and source hashes required")
    run = await session.get(EvaluationRun, run_id, with_for_update=True)
    if not run or run.state not in {"completed", "failed", "cancelled"}:
        raise ValueError("Only terminal tasks can be recovered")
    snap = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
    if checksum(snap.canonical_body) != snap.sha256:
        raise ValueError("Run snapshot hash mismatch")
    tasks = [t for t in snap.canonical_body["inputs"]["tasks"] if t["dataset"] == dataset]
    if len(tasks) != 1:
        raise ValueError("Ambiguous dataset")
    parent = await session.scalar(
        select(UnifiedCollection).where(
            UnifiedCollection.run_id == run_id,
            UnifiedCollection.collection_key == tasks[0]["task_id"],
        )
    )
    if not parent:
        raise ValueError("Original collection required")
    original = await asyncio.to_thread(read_manifest, settings, parent)
    recovered = json.loads(raw)
    before = {(c["case_id"], c["attempt"]): c for c in original["cases"]}
    after = {(c["case_id"], c["attempt"]): c for c in recovered["cases"]}
    if len(after) != len(recovered["cases"]) or before.keys() != after.keys():
        raise ValueError("Recovery must preserve original attempts exactly")
    allowed = {
        "harbor_artifact",
        "score",
        "score_name",
        "score_source",
        "input_tokens",
        "output_tokens",
    }
    actual_hashes = []
    for identity, case in after.items():
        if {k: v for k, v in before[identity].items() if k not in allowed} != {
            k: v for k, v in case.items() if k not in allowed
        }:
            raise ValueError("Recovery changed original execution facts")
        files = case.get("harbor_artifact", {}).get("files", {})
        native = json.loads(files["result.json"])
        name = case.get("trial_name") or case.get("trial_dir")
        expected_name = case["case_id"]
        if (
            native.get("trial_name") != name
            or native.get("task_name") not in {expected_name, "automationbench/" + expected_name}
            or native.get("finished_at") != case.get("finished_at")
        ):
            raise ValueError("Native recovery identity mismatch")
        check = copy.deepcopy(case)
        check["score"] = None
        from autoeval.result_identity import apply_automationbench_accuracy

        apply_automationbench_accuracy(check)
        if check.get("score") != case.get("score"):
            raise ValueError("Recovered score differs from native evidence")
        for path in ("result.json", "verifier/reward.json"):
            actual_hashes.append(
                {
                    "trial": name,
                    "path": path,
                    "sha256": hashlib.sha256(files[path].encode()).hexdigest(),
                }
            )
    if sorted(source_hashes, key=lambda x: (x["trial"], x["path"])) != sorted(
        actual_hashes, key=lambda x: (x["trial"], x["path"])
    ):
        raise ValueError("Recovery source hash manifest mismatch")
    summary = scored_summary(raw, tasks[0])
    digest = hashlib.sha256(raw).hexdigest()
    provenance = {
        "reason": reason,
        "method": "native-score-recovery.v1",
        "actor": "local-operator",
        "parent_collection_id": str(parent.id),
        "parent_sha256": parent.sha256,
        "snapshot_sha256": snap.sha256,
        "source_files": source_hashes,
    }
    existing = await session.scalar(
        select(ResultArchiveRevision).where(
            ResultArchiveRevision.run_id == run_id,
            ResultArchiveRevision.dataset_key == dataset,
            ResultArchiveRevision.sha256 == digest,
        )
    )
    if existing:
        await asyncio.to_thread(read_manifest, settings, existing)
        return existing
    key = f"result-revisions/{run_id}/{dataset}/{digest}.json"
    await asyncio.to_thread(write_manifest, settings, key, raw)
    row = ResultArchiveRevision(
        run_id=run_id,
        dataset_key=dataset,
        parent_collection_id=parent.id,
        object_key=key,
        sha256=digest,
        provenance=provenance,
        summary=summary,
    )
    session.add(row)
    await session.flush()
    return row


async def publish_task_report(session, settings, run_id, *, revision_ids=()):
    """Explicit revisions; never choose a recovery implicitly by latest timestamp."""
    run = await session.get(EvaluationRun, run_id, with_for_update=True)
    if not run or run.state not in {"completed", "failed", "cancelled"}:
        raise ValueError("Task must be terminal")
    snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
    frozen = snapshot.canonical_body
    if checksum(frozen) != snapshot.sha256:
        raise ValueError("Run snapshot hash mismatch")
    revisions = {}
    for identifier in revision_ids:
        r = await session.get(ResultArchiveRevision, uuid.UUID(str(identifier)))
        if not r or r.run_id != run_id or r.dataset_key in revisions:
            raise ValueError("Invalid recovery revision selection")
        revisions[r.dataset_key] = r
    datasets = []
    for task in frozen["inputs"]["tasks"]:
        row = revisions.get(task["dataset"])
        recovered = row is not None
        if row is None:
            row = await session.scalar(
                select(UnifiedCollection).where(
                    UnifiedCollection.run_id == run_id,
                    UnifiedCollection.collection_key == task["task_id"],
                )
            )
        if row is None:
            child = await session.scalar(
                select(DatasetExecution).where(
                    DatasetExecution.run_id == run_id, DatasetExecution.task_id == task["task_id"]
                )
            )
            summary = (child.summary if child else None) or {
                "validity": "failed",
                "accuracy": None,
                "scoring_status": "failed",
            }
            ref = None
        else:
            body = await asyncio.to_thread(read_manifest, settings, row)
            summary = scored_summary(canonical_manifest(body), task)
            ref = {
                "id": str(row.id),
                "object_key": row.object_key,
                "sha256": row.sha256,
                "kind": "recovery" if recovered else "original",
            }
        datasets.append(
            {
                "dataset_key": task["dataset"],
                "summary": summary,
                "validity": summary["validity"],
                "context": dataset_context(frozen, task),
                "archive": ref,
                "provenance": row.provenance if recovered else None,
            }
        )
    complete = all(d["validity"] == "complete" for d in datasets)
    summary = {
        "accuracy": None,
        "dataset_count": len(datasets),
        "scoring_status": "succeeded" if complete else "partial",
        **{
            k: sum(d["summary"].get(k, 0) or 0 for d in datasets)
            for k in (
                "expected_samples",
                "executed_attempts",
                "successful_samples",
                "failed_samples",
                "missing_samples",
            )
        },
    }
    old = await session.scalar(select(EvaluationReport).where(EvaluationReport.run_id == run_id))
    previous = await asyncio.to_thread(read_manifest, settings, old) if old else None
    body = {
        "schema_version": "task-report.v2",
        "run_id": str(run_id),
        "snapshot_sha256": snapshot.sha256,
        "execution_origin": frozen["execution_origin"],
        "validity": "complete" if complete else "partial",
        "summary": summary,
        "datasets": datasets,
        "historical_task_state": previous.get("historical_task_state", run.state)
        if previous
        else run.state,
    }
    summary["dataset_results"] = [
        {"dataset_key": d["dataset_key"], "summary": d["summary"]} for d in datasets
    ]
    digest = checksum(body)
    if old:
        if old.sha256 != digest:
            raise ValueError(
                "Task already has an immutable report; publication would overwrite history"
            )
        await asyncio.to_thread(read_manifest, settings, old)
        return old
    key = f"reports/{run_id}/{digest}.json"
    await asyncio.to_thread(write_manifest, settings, key, canonical_manifest(body))
    row = EvaluationReport(
        run_id=run_id,
        validity=body["validity"],
        snapshot_sha256=snapshot.sha256,
        summary=summary,
        object_key=key,
        sha256=digest,
        execution_origin=frozen["execution_origin"],
    )
    session.add(row)
    await session.flush()
    return row


async def apply_recovered_state(session, settings, report):
    """Append recovery event, then update current projections; never erase failure history."""
    from datetime import UTC, datetime

    from autoeval.models import RunEvent
    from autoeval.reporting.report_integrity import report_evidence_status
    from autoeval.task_monitor import MonitorBinding, MonitorSnapshot

    run = await session.get(EvaluationRun, report.run_id, with_for_update=True)
    snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run.id))
    if (
        report.validity != "complete"
        or await report_evidence_status(settings, report, run, snapshot) != "verified"
    ):
        raise ValueError("Verified complete report required for recovery completion")
    events = list(
        await session.scalars(
            select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)
        )
    )
    if any(
        e.type == "results_recovered" and e.body.get("report_sha256") == report.sha256
        for e in events
    ):
        return
    if run.state not in {"failed", "completed"}:
        raise ValueError("Only terminal failed/completed tasks can be repaired")
    body = await asyncio.to_thread(read_manifest, settings, report)
    if body.get("schema_version") != "task-report.v2":
        raise ValueError("Dataset report required")
    prior = []
    for section in body["datasets"]:
        child = await session.scalar(
            select(DatasetExecution).where(
                DatasetExecution.run_id == run.id,
                DatasetExecution.payload["dataset"].astext == section["dataset_key"],
            )
        )
        if child is None:
            raise ValueError("Dataset child missing")
        prior.append(
            {
                "child_id": str(child.id),
                "dataset": section["dataset_key"],
                "state": child.state,
                "summary": child.summary,
            }
        )
        child.state = "succeeded"
        child.summary = {
            **section["summary"],
            "recovery_report_id": str(report.id),
            "recovery_report_sha256": report.sha256,
        }
        bindings = list(
            await session.scalars(select(MonitorBinding).where(MonitorBinding.run_id == run.id))
        )
        for binding in bindings:
            if binding.identity.get("dataset") != section["dataset_key"]:
                continue
            projection = {
                **(binding.latest or {}),
                "collection_status": "archived_cases",
                "source": "archived_case_executions",
                "snapshot_kind": "final",
                "stale": False,
                "tool_status": "succeeded",
                "finish_count": section["summary"]["observed_cases"],
                "total_count": section["summary"]["expected_cases"],
                "observed_at": datetime.now(UTC).isoformat(),
                "diagnostics": ["恢复归档核验完成；此为同次执行的归档结果，不是新增实时采集。"],
                "recovery_report_id": str(report.id),
                "recovery_report_sha256": report.sha256,
            }
            raw = canonical_manifest(
                {
                    "projection": projection,
                    "recovery_report_id": str(report.id),
                    "report_sha256": report.sha256,
                }
            )
            digest = hashlib.sha256(raw).hexdigest()
            key = f"monitor/{run.id}/{binding.id}/{digest}.json"
            await asyncio.to_thread(write_manifest, settings, key, raw)
            binding.latest = projection
            session.add(
                MonitorSnapshot(binding_id=binding.id, object_key=key, sha256=digest, kind="final")
            )
    old_state = run.state
    run.state = "completed"
    run.projection_version = (
        max(run.projection_version or 0, max((e.seq for e in events), default=0)) + 1
    )
    session.add(
        RunEvent(
            run_id=run.id,
            seq=run.projection_version,
            type="results_recovered",
            body={
                "previous_state": old_state,
                "previous_datasets": prior,
                "report_id": str(report.id),
                "report_sha256": report.sha256,
                "reason": "Recovered original native scoring evidence; no new execution or model calls",
            },
        )
    )
