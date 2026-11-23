"""Compute a follow-up scope from frozen inputs and reconciled job evidence."""

from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from autoeval.catalog.standard_inputs import digest
from autoeval.evaluation.models import (
    CapacityLease,
    DatasetExecution,
    DatasetExecutionEnvironment,
    ExecutionRound,
    ExecutionShard,
    ExecutionShardEnvironment,
)
from autoeval.evaluation.resume_budget import (
    follow_up_budget_blocker,
    follow_up_target_blocker,
    round_budget_snapshot,
)
from autoeval.evaluation.resume_evidence import (
    classify_sample,
    observe_archived_attempt,
    terminal_attempt_group,
)
from autoeval.evaluation.resume_selection import remaining_payloads
from autoeval.evaluation.resume_submission import ConfirmedScope
from autoeval.infrastructure.models import RunSnapshot
from autoeval.planning.planning_transport import execution_template
from autoeval.reporting.models import CaseExecutionRecord


async def preview_scope(session, settings, run, operation, target):
    if run is None or run.trigger_scope != "local-operator:orchestration":
        raise HTTPException(404, "Evaluation task not found")
    snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run.id))
    if snapshot is None or snapshot.sha256 != digest(snapshot.canonical_body):
        raise HTTPException(409, "Frozen snapshot unavailable")
    rounds = list(
        await session.scalars(
            select(ExecutionRound)
            .where(ExecutionRound.run_id == run.id)
            .order_by(ExecutionRound.number)
        )
    )
    jobs = list(
        await session.scalars(select(DatasetExecution).where(DatasetExecution.run_id == run.id))
    )
    if rounds:
        jobs.extend(
            await session.scalars(
                select(ExecutionShard)
                .join(ExecutionRound, ExecutionRound.id == ExecutionShard.round_id)
                .where(ExecutionRound.run_id == run.id)
                .order_by(ExecutionRound.number, ExecutionShard.position)
            )
        )
    leases = {
        lease.owner_id: lease.released
        for lease in await session.scalars(
            select(CapacityLease).where(CapacityLease.owner_id.in_([job.id for job in jobs]))
        )
    }
    latest_jobs = {}
    for job in jobs:
        for sample in job.payload["samples"]:
            latest_jobs[(job.payload["dataset"], sample["sample_id"])] = (job, sample)

    attempts = defaultdict(list)
    for record in await session.scalars(
        select(CaseExecutionRecord)
        .where(CaseExecutionRecord.run_id == run.id)
        .order_by(CaseExecutionRecord.attempt_no)
    ):
        attempts[(record.dataset_key, record.sample_id)].append(record)

    blockers = []
    if run.state not in {"completed", "failed", "cancelled"}:
        blockers.append("source_active")
    if operation == "resume" and run.state != "cancelled":
        blockers.append("source_not_cancelled")
    owners = [job.id for job in jobs]
    environments_pending = False
    for model, owner_column in (
        (DatasetExecutionEnvironment, DatasetExecutionEnvironment.dataset_execution_id),
        (ExecutionShardEnvironment, ExecutionShardEnvironment.shard_id),
    ):
        if await session.scalar(select(owner_column).where(
            owner_column.in_(owners), model.state != "cleaned"
        ).limit(1)):
            environments_pending = True
            break
    if environments_pending or any(not released for released in leases.values()):
        blockers.append("cleanup_pending")
    manual_retry = operation == "case_retry" and bool(target)
    warnings = []
    shards = []
    rows = []
    for task in snapshot.canonical_body["inputs"]["tasks"]:
        selected = set()
        for sample in task["samples"]:
            identity = (task["dataset"], sample["sample_id"])
            if target and identity != (target["dataset_key"], target["sample_id"]):
                continue
            job, job_sample = latest_jobs.get(identity, (None, {}))
            same_sample = job_sample.get("sha256") == sample["sha256"]
            history = attempts[identity]
            reconciled = job is not None and (
                job.state == "succeeded"
                or (job.summary or {}).get("dispatch_reconciled") is True
                or identity[1] in (job.summary or {}).get("confirmed_not_dispatched", ())
                or (job.state == "cancelled" and job.started_at is None and job.id not in leases)
            )
            collection_key = f"round-shard:{job.id}" if isinstance(job, ExecutionShard) else None
            records = [
                record
                for record in history
                if (record.tool_metadata or {}).get("execution_collection_key") == collection_key
            ]
            if job is not None and job.state in {"cancelled", "failed"}:
                reconciled = reconciled or terminal_attempt_group(records, task["attempts"])
            observations = (
                [await observe_archived_attempt(settings, record) for record in records]
                if reconciled and same_sample
                else []
            )
            decision = classify_sample(
                observations,
                expected_attempts=task["attempts"],
                dispatch_reconciled=reconciled
                and same_sample
                and not any(record.state == "started" for record in history),
            )
            rows.append(
                {
                    "dataset_key": identity[0],
                    "sample_id": identity[1],
                    "sample_sha256": sample["sha256"],
                    "has_attempts": bool(history),
                    "evidence_sha256": [record.sha256 for record in records],
                    **asdict(decision),
                }
            )
            if decision.category == "unknown":
                if (
                    manual_retry
                    and decision.reason == "dispatch_unresolved"
                    and job is not None
                    and same_sample
                    and job.state in {"failed", "cancelled"}
                    and not any(record.state == "started" for record in records)
                ):
                    selected.add(identity[1])
                    warnings.append("previous_dispatch_unknown")
                elif "samples_unresolved" not in blockers:
                    blockers.append("samples_unresolved")
            elif manual_retry or decision.category != "reusable":
                selected.add(identity[1])
        if task.get("execution_template") and (
            selected or (target and target["dataset_key"] == task["dataset"])
        ):
            try:
                current = execution_template(settings, task["assigned_resource_id"], task)
            except (KeyError, ValueError, OSError):
                current = None
            if current != task["execution_template"]:
                if manual_retry and current and selected:
                    task = {**task, "execution_template": current}
                    warnings.append("using_current_template")
                elif "resource_changed" not in blockers:
                    blockers.append("resource_changed")
        shards.extend(remaining_payloads(task, selected))
    if target and not rows:
        raise HTTPException(404, "Sample not in frozen selection")
    if shards and not blockers:
        target_blocker = await follow_up_target_blocker(session, settings, snapshot.canonical_body)
        if target_blocker:
            blockers.append(target_blocker)
        budget_blocker = await follow_up_budget_blocker(
            session, settings, run.id,
            round_budget_snapshot(snapshot.canonical_body, operation, datetime.now(UTC)),
        )
        if budget_blocker:
            blockers.append(budget_blocker)
    selection = {
        "source_round": rounds[-1].number if rounds else 1,
        "operation": operation,
        "target": target,
        "samples": rows,
        "blockers": blockers,
        "sample_count": sum(len(shard["samples"]) for shard in shards),
    }
    if warnings:
        selection["warnings"] = warnings
    if "using_current_template" in warnings:
        selection["execution_template_sha256"] = digest(shards[0]["execution_template"])
    return ConfirmedScope(
        snapshot.sha256, digest({"snapshot": snapshot.sha256, **selection}), selection, shards
    )
