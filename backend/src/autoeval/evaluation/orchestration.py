"""Durable multi-dataset execution with capacity leases and isolated child jobs.

The polling loop owns remote I/O through the planning transport adapters and
keeps Temporal concerns in the activity wrapper at the bottom of this file.
"""

import asyncio
import hashlib
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import select, text
from temporalio import activity

from autoeval.catalog.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.catalog.standard_inputs import digest
from autoeval.evaluation.isolated_cleanup import reclaim_child
from autoeval.evaluation.models import (
    CapacityLease,
    DatasetExecution,
    DatasetExecutionEnvironment,
    ExecutionRound,
    ExecutionShard,
    ExecutionShardEnvironment,
)
from autoeval.evaluation.resource_allocation import acquire, demand_for, release, resource_for_task
from autoeval.evaluation.resume_budget import (
    follow_up_budget_blocker,
    follow_up_target_blocker,
    round_budget_snapshot,
)
from autoeval.evaluation.resume_evidence import ConfirmedEvidenceChanged, verify_confirmed_reuse
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.contracts import JobRef
from autoeval.infrastructure.db import create_database
from autoeval.infrastructure.domain import DATASET_ACTIVE, DATASET_TERMINAL, RUN_TERMINAL
from autoeval.infrastructure.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.infrastructure.secrets import FileSecretStore
from autoeval.planning.artifacts import artifact
from autoeval.planning.models import PlanningArtifact
from autoeval.planning.planning_transport import (
    HarborDaemonUnavailable,
    execution_template,
    isolated_transport,
    transport,
)
from autoeval.reporting.unified_outputs import InvalidUnifiedOutput, archive_output
from autoeval.resources.models import TargetBinding


async def keep_heartbeat(callback, awaitable, *, interval_seconds=30):
    """Keep the activity alive while long archives or reports hold the worker."""
    stop = asyncio.Event()

    async def beat():
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                callback()

    task = asyncio.create_task(beat())
    try:
        return await awaitable
    finally:
        stop.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


TERMINAL = set(DATASET_TERMINAL)


async def update_child(sessions, owner, **values):
    child_id = owner.id
    env_model = (
        ExecutionShardEnvironment
        if isinstance(owner, ExecutionShard)
        else DatasetExecutionEnvironment
    )
    async with sessions() as session, session.begin():
        child = await session.get(type(owner), child_id, with_for_update=True)
        if values.get("state") in TERMINAL:
            environment = await session.get(env_model, child_id)
            if environment is not None:
                environment.state = "cleanup_pending"
        for key, value in values.items():
            setattr(child, key, value)


async def advance_run(session, run, state, details=None):
    if run.state != state:
        run.state = state
        run.projection_version += 1
        session.add(
            RunEvent(run_id=run.id, seq=run.projection_version, type=state, body=details or {})
        )


async def execute(sessions, settings, run_id, heartbeat=lambda: None, *, round_id=None):
    job_query = (
        select(ExecutionShard)
        .where(ExecutionShard.round_id == round_id)
        .order_by(ExecutionShard.position)
        if round_id
        else select(DatasetExecution).where(DatasetExecution.run_id == run_id)
    )
    env_model = ExecutionShardEnvironment if round_id else DatasetExecutionEnvironment
    async with sessions() as session:
        existing_run = await session.get(EvaluationRun, run_id)
        if existing_run and existing_run.state in RUN_TERMINAL:
            return
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        if not snapshot or snapshot.sha256 != digest(snapshot.canonical_body):
            raise ValueError("Frozen snapshot integrity mismatch")
        frozen = snapshot.canonical_body
        execution_snapshot = frozen
        current = await session.get_one(ExecutionRound, round_id) if round_id else None
        if current is not None:
            execution_snapshot = round_budget_snapshot(frozen, current.operation, current.created_at)
        if current is not None and existing_run.cancel_requested_at is None:
            started = await session.scalar(
                job_query.where(ExecutionShard.started_at.is_not(None)).limit(1)
            )
            if current.operation == "resume" and started is None:
                try:
                    await keep_heartbeat(
                        heartbeat, verify_confirmed_reuse(session, settings, current)
                    )
                except ConfirmedEvidenceChanged:
                    await stop_before_dispatch(sessions, run_id, round_id)
                    return
        from autoeval.billing.transport import budget_ignored

        ignore_budget = budget_ignored(frozen)
        inputs = frozen["inputs"]
        isolated = all(t.get("execution_template") for t in inputs["tasks"])
        adapter = None
        initial_children = list(await session.scalars(job_query))
        if round_id and not initial_children:
            from autoeval.evaluation.resume_finish import finish_round

            await finish_round(sessions, settings, run_id, round_id, frozen, [], False)
            return
        adapters = {}
        for child in initial_children:
            item = child.payload
            if isolated:
                environment = await session.get(env_model, child.id)
                adapters[child.id] = await isolated_transport(
                    session,
                    settings,
                    item["assigned_resource_id"],
                    child.id,
                    item["execution_template"],
                    container_id=environment.container_id if environment else None,
                )
                continue
            if not item.get("assigned_resource_id") and adapter is None:
                adapter = await transport(session, settings, inputs)
            adapters[child.id] = (
                await transport(
                    session,
                    settings,
                    {
                        **inputs,
                        "resource_id": item["assigned_resource_id"],
                        "resource_kind": item["assigned_resource_kind"],
                    },
                )
                if item.get("assigned_resource_id")
                else adapter
            )
        target = await session.get(TargetBinding, inputs["target_id"])
        secret = FileSecretStore(settings.secret_store_path).get(target.credential_ref)
    while True:
        heartbeat()
        async with sessions() as session:
            run = await session.get(EvaluationRun, run_id)
            budget_config = getattr(settings, "billing_execution_config", None)
            if (budget_config or ignore_budget) and run.cancel_requested_at is None:
                import json
                from pathlib import Path

                deadline = datetime.fromisoformat(
                    execution_snapshot["model_budget"]["execution_deadline"]
                    if ignore_budget
                    else (frozen.get("model_budget") or {}).get("deadline")
                    or json.loads(Path(budget_config).read_text())["deadline"]
                )
                if datetime.now(UTC) >= deadline:
                    run.cancel_requested_at = datetime.now(UTC)
                    await advance_run(
                        session, run, "cancelling", {"reason": "budget_execution_deadline"}
                    )
                    await session.commit()
            cancelled = run.cancel_requested_at is not None
            children = list(await session.scalars(job_query))
        if not round_id:
            by_id = {c.task_id: c for c in children}
            children = [by_id[t["task_id"]] for t in inputs["tasks"]]
        for child in children:
            adapter = adapters[child.id]
            if child.state == "pending" and cancelled:
                await update_child(
                    sessions, child, state="cancelled", finished_at=datetime.now(UTC)
                )
                child.state = "cancelled"
                child.finished_at = datetime.now(UTC)
            if child.state not in DATASET_ACTIVE:
                continue
            if isolated:
                async with sessions() as session:
                    environment = await session.get(env_model, child.id)
                if environment and environment.state == "creating":
                    await update_child(
                        sessions,
                        child,
                        state="cancelled" if cancelled else "pending",
                        **({"finished_at": datetime.now(UTC)} if cancelled else {}),
                    )
                    child.state = "cancelled" if cancelled else "pending"
                    continue
            from autoeval.billing.transport import execution_route

            child_route = execution_route(
                settings,
                run_id,
                inputs["target_id"],
                child.payload["dataset"],
                ignore_budget=ignore_budget,
            )
            child_secret = child_route["api_key"] if child_route else secret
            job = JobRef(external_job_id=str(child.id), submission_key=str(child.id))
            try:
                observation = (
                    await adapter.cancel(job, "cancel:" + str(child.id))
                    if cancelled
                    else await adapter.status(job)
                )
            except (OSError, ValueError, RuntimeError):
                if not isolated:
                    raise
                await update_child(
                    sessions,
                    child,
                    state="unresolved",
                    summary={"reason": "SSH execution state could not be verified"},
                )
                child.state = "unresolved"
                continue
            if observation.state in {"unknown", "cleaned"}:
                await update_child(
                    sessions,
                    child,
                    state="unresolved",
                    summary={
                        "reason": "Remote state uncertain; lease retained, no automatic resubmission"
                    },
                )
                child.state = "unresolved"
                continue
            if observation.state not in TERMINAL:
                from autoeval.planning.planning_observations import publish_lifecycle

                await publish_lifecycle(sessions, settings, run_id, child, observation.state)
                if observation.state == "running":
                    progress_reader = getattr(adapter, "progress", None)
                    if progress_reader:
                        try:
                            progress = await progress_reader(job)
                            if progress:
                                from autoeval.planning.planning_observations import publish

                                await publish(sessions, settings, run_id, child.id, progress)
                                await update_child(sessions, child, summary={"progress": progress})
                        except (OSError, ValueError, RuntimeError):
                            pass  # Observation failure never resubmits the model task.
                continue
            from autoeval.planning.planning_observations import publish_lifecycle

            final_reader = getattr(adapter, "progress", None)
            if final_reader:
                try:
                    from autoeval.planning.planning_observations import publish

                    await publish(sessions, settings, run_id, child.id, await final_reader(job))
                except (OSError, ValueError, RuntimeError):
                    pass
            await publish_lifecycle(
                sessions, settings, run_id, child, observation.state, final=True
            )
            try:
                state, summary = await archive_terminal_child(
                    sessions,
                    settings,
                    run_id,
                    child,
                    adapter,
                    job,
                    observation.state,
                    secret,
                    child_secret,
                    heartbeat,
                    reason=getattr(observation, "reason", None),
                )
            except Exception as exc:  # Isolated jobs retain evidence for retry.
                if not isolated:
                    raise
                if not (child.summary or {}).get("archive_pending"):
                    await update_child(
                        sessions,
                        child,
                        summary={
                            **(child.summary or {}),
                            "archive_pending": True,
                            "archive_error_type": type(exc).__name__,
                        },
                    )
                continue
            if state == "failed" and summary is None:
                remote_reason = getattr(observation, "reason", None)
                reason = (
                    remote_reason
                    if remote_reason
                    in {"controlled_job_failed", "native_unified_result_missing_or_ambiguous"}
                    else "native_execution_failed"
                )
                summary = {"validity": "failed", "reason": reason}
            await update_child(
                sessions, child, state=state, summary=summary, finished_at=datetime.now(UTC)
            )
            child.state = state
            child.summary = summary
            child.finished_at = datetime.now(UTC)
        cleanup_pending = await clean_terminal_jobs(
            sessions, settings, children, adapters, env_model, isolated
        )
        if all(c.state in TERMINAL for c in children) and (
            not cleanup_pending
            or not (round_id or getattr(settings, "evaluation_follow_up_enabled", False))
        ):
            if round_id:
                from autoeval.evaluation.resume_finish import finish_round

                await finish_round(
                    sessions, settings, run_id, round_id, frozen, children, cancelled
                )
            else:
                await finish(sessions, settings, run_id, frozen, children, cancelled)
            return
        active = sum(c.state in DATASET_ACTIVE for c in children)
        active_tasks = {c.task_id for c in children if c.state in DATASET_ACTIVE}
        for child in children:
            adapter = adapters[child.id]
            if cancelled or active >= inputs["dataset_concurrency"]:
                break
            if child.state != "pending" or child.task_id in active_tasks:
                continue
            async with sessions() as session, session.begin():
                current_run = await session.get(EvaluationRun, run_id, with_for_update=True)
                if current_run.cancel_requested_at is not None:
                    cancelled = True
                    break
                if round_id:
                    blocker = await follow_up_target_blocker(session, settings, frozen)
                    blocker = blocker or await follow_up_budget_blocker(
                        session, settings, run_id, execution_snapshot
                    )
                    if blocker:
                        stored = await session.get_one(type(child), child.id, with_for_update=True)
                        stored.state = "failed"
                        stored.finished_at = datetime.now(UTC)
                        stored.summary = {"reason": blocker, "dispatch_reconciled": True}
                        continue
                if not await acquire(
                    session,
                    child.id,
                    resource_for_task(frozen["resource"], child.task_id),
                    demand_for(child.payload),
                ):
                    if inputs["dataset_concurrency"] == 1:
                        break  # Preserve dataset order while the first pending child waits.
                    continue
                stored = await session.get(type(child), child.id, with_for_update=True)
                if isolated and await session.get(env_model, child.id) is None:
                    session.add(
                        env_model(
                            **(
                                {"shard_id": child.id}
                                if round_id
                                else {"dataset_execution_id": child.id}
                            ),
                            resource_id=uuid.UUID(child.payload["assigned_resource_id"]),
                            template=child.payload["execution_template"],
                            state="creating",
                        )
                    )
                stored.state = "submitting"
                stored.started_at = datetime.now(UTC)
            # The durable submitting intent precedes network I/O. A lost reply is reconciled
            # by lookup, never by issuing a new model-generating submission.
            try:
                from autoeval.planning.planning_observations import (
                    case_contract,
                    harbor_dispatch_contract,
                )

                contract = case_contract(child.payload)
                harbor_contract = harbor_dispatch_contract(child.payload)
                from autoeval.billing.transport import execution_route, route_compilation

                route = execution_route(
                    settings,
                    run_id,
                    inputs["target_id"],
                    child.payload["dataset"],
                    ignore_budget=ignore_budget,
                )
                compilation = (
                    route_compilation(child.payload["compilation"], route)
                    if route
                    else child.payload["compilation"]
                )
                from autoeval.evaluation.resource_allocation import execution_compilation

                compilation = execution_compilation(compilation)
                execution_secret = route["api_key"] if route else secret
                if isolated:
                    if (
                        execution_template(
                            settings, child.payload["assigned_resource_id"], child.payload
                        )
                        != child.payload["execution_template"]
                    ):
                        await update_child(
                            sessions,
                            child,
                            state="failed",
                            finished_at=datetime.now(UTC),
                            summary={"reason": "SSH execution template changed"},
                        )
                        continue
                    try:
                        container_id = await adapter.ensure()
                    except HarborDaemonUnavailable as exc:
                        async with sessions() as session, session.begin():
                            environment = await session.get(env_model, child.id)
                            environment.container_id = exc.container_id
                        await update_child(
                            sessions,
                            child,
                            state="failed",
                            finished_at=datetime.now(UTC),
                            summary={"reason": "Harbor private Docker daemon is unavailable"},
                        )
                        await reclaim_child(sessions, settings, child.id, model=env_model)
                        continue
                    async with sessions() as session, session.begin():
                        current_run = await session.get(EvaluationRun, run_id, with_for_update=True)
                        environment = await session.get(env_model, child.id)
                        environment.container_id = container_id
                        cancelled = current_run.cancel_requested_at is not None
                        if cancelled:
                            stored = await session.get(type(child), child.id, with_for_update=True)
                            stored.state = "cancelled"
                            stored.finished_at = datetime.now(UTC)
                            environment.state = "cleanup_pending"
                        else:
                            environment.state = "submitting"
                    if cancelled:
                        await reclaim_child(sessions, settings, child.id, model=env_model)
                        break
                await adapter.submit(
                    {
                        "kind": "adaptor",
                        "compilation": compilation,
                        "tool": child.payload["tool"],
                        "credential": execution_secret,
                        **(
                            {"harbor_dispatch_contract": harbor_contract} if harbor_contract else {}
                        ),
                        **({"case_contract": contract} if contract else {}),
                    },
                    str(child.id),
                )
                await update_child(sessions, child, state="running")
            except Exception:  # noqa: BLE001 -- isolate third-party errors without leaking credentials
                await update_child(sessions, child, state="unresolved")
            active_tasks.add(child.task_id)
            active += 1
        async with sessions() as session, session.begin():
            run = await session.get(EvaluationRun, run_id, with_for_update=True)
            if run.cancel_requested_at:
                state = "cancelling"
            elif active:
                state = "running"
            elif cleanup_pending:
                state = "aggregating"
            else:
                state = "queued"
            if round_id:
                execution_round = await session.get_one(ExecutionRound, round_id)
                execution_round.state = state
                execution_round.cancel_requested_at = run.cancel_requested_at
            await advance_run(
                session, run, state, {"cleanup_pending": True} if cleanup_pending else None
            )
        await asyncio.sleep(2)


async def archive_terminal_child(
    sessions,
    settings,
    run_id,
    child,
    adapter,
    job,
    state,
    secret,
    child_secret,
    heartbeat,
    *,
    reason=None,
):
    summary = None
    log_reader = getattr(adapter, "collect_log", None)
    if log_reader:
        from autoeval.reporting.models import UnifiedArtifact

        log_key = "planning-log:" + str(child.id)
        async with sessions() as session, session.begin():
            existing_log = await session.scalar(
                select(UnifiedArtifact).where(
                    UnifiedArtifact.run_id == run_id,
                    UnifiedArtifact.collection_key == log_key,
                )
            )
            if existing_log is None:
                observed_log = await log_reader(job)
                content = (
                    observed_log["content"]
                    .replace(secret, "[REDACTED]")
                    .replace(child_secret, "[REDACTED]")
                )
                file = {
                    "path": "job.log",
                    "content": content,
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "truncated": observed_log["truncated"],
                }
                bundle = {
                    "run_id": str(run_id),
                    "child_id": str(child.id),
                    "source": "adaptor_tool_log",
                    "files": [file],
                }
                sha = digest(bundle)
                key = f"execution-logs/{run_id}/{child.id}/{sha}.json"
                await asyncio.to_thread(write_manifest, settings, key, canonical_manifest(bundle))
                await asyncio.to_thread(
                    read_manifest, settings, SimpleNamespace(object_key=key, sha256=sha)
                )
                session.add(
                    UnifiedArtifact(
                        run_id=run_id,
                        collection_key=log_key,
                        object_key=key,
                        sha256=sha,
                        manifest=bundle,
                    )
                )
    round_id = getattr(child, "round_id", None)
    result = await adapter.collect(job)
    collected = result.get("result") or {}
    if state == "succeeded" and collected.get("unified_result") is None:
        raise ValueError("Successful job has no unified result")
    if collected.get("native_files") or collected.get("harbor_native_trials"):
        from autoeval.planning.planning_observations import archive_native

        await archive_native(sessions, settings, run_id, child, collected, child_secret)
    if collected.get("unified_result") is None and collected.get("harbor_native_trials"):
        from autoeval.reporting.result_identity import recover_cancelled_harbor_cases

        collected["unified_result"] = recover_cancelled_harbor_cases(
            child.payload, collected["harbor_native_trials"], result.get("sample_dispatch")
        )
    unified = collected.get("unified_result")
    if collected.get("native_files") and (
        unified is None or unified.get("score_source") == "aisbench_native_prediction_scoring"
    ):
        from autoeval.planning.planning_observations import terminal_prediction_failures

        failures = terminal_prediction_failures(child.payload, collected)
        if failures and unified:
            unified["cases"].extend(failures["cases"])
            unified["case_count"] = len(unified["cases"])
        elif failures:
            collected["unified_result"] = failures
    if collected.get("unified_result") is not None:
        from autoeval.planning.planning_observations import publish

        reader = getattr(adapter, "progress", None)
        if reader:
            await publish(sessions, settings, run_id, child.id, await reader(job))
        unified = collected["unified_result"]
        async with sessions() as session, session.begin():
            await artifact(
                session,
                settings,
                "raw_result",
                {"run_id": str(run_id), "task_id": child.task_id, "result": unified},
            )
        try:
            from autoeval.reporting.result_identity import normalize_result_identities

            try:
                unified = normalize_result_identities(
                    unified,
                    child.payload["dataset"],
                    child.payload["compilation"]["config"],
                    child.payload["samples"],
                )
            except ValueError as exc:
                raise InvalidUnifiedOutput(str(exc)) from exc
            raw = canonical_manifest(unified)
            summary = await keep_heartbeat(
                heartbeat,
                archive_output(
                    sessions,
                    settings,
                    run_id,
                    f"round-shard:{child.id}" if round_id else child.task_id,
                    raw,
                    {child.payload["dataset"]: [s["sample_id"] for s in child.payload["samples"]]},
                    child.payload["dataset"],
                    append_attempts=round_id is not None,
                ),
            )
        except InvalidUnifiedOutput:
            summary = {
                "validity": "failed",
                "reason": "Result identity or evidence validation failed; raw result preserved",
            }
        if child.payload["dataset"] == "GPQA":
            summary = gpqa_report_summary(summary, unified, child.payload)
        if collected.get("tool_exit_code", 0) != 0:
            summary = {
                **summary,
                "validity": "partial",
                "tool_exit_code": collected["tool_exit_code"],
                "diagnostic": collected.get("diagnostic"),
            }
        elif collected.get("diagnostic") and summary["validity"] != "complete":
            summary = {**summary, "tool_exit_code": 0, "diagnostic": collected["diagnostic"]}
        if state == "succeeded" and summary["validity"] != "complete":
            state = "failed"
    if state == "cancelled" and reason == "cancelled_before_launch":
        summary = {"reason": reason, "dispatch_reconciled": True}
    if result.get("sample_dispatch") is not None:
        from autoeval.planning.planning_observations import archive_dispatch

        not_dispatched = await archive_dispatch(
            sessions, settings, run_id, child, result["sample_dispatch"]
        )
        summary = {**(summary or {}), "confirmed_not_dispatched": not_dispatched}
    return state, summary


async def stop_before_dispatch(sessions, run_id, round_id):
    async with sessions() as session, session.begin():
        run = await session.get_one(EvaluationRun, run_id, with_for_update=True)
        current = await session.get_one(ExecutionRound, round_id, with_for_update=True)
        shards = list(
            await session.scalars(
                select(ExecutionShard).where(ExecutionShard.round_id == round_id).with_for_update()
            )
        )
        if any(shard.started_at is not None for shard in shards):
            raise RuntimeError("Cannot invalidate a scope after dispatch")
        now = datetime.now(UTC)
        for shard in shards:
            shard.state = "cancelled"
            shard.finished_at = now
            shard.summary = {"reason": "confirmed_evidence_changed"}
        current.state = "cancelled"
        current.cancelled_at = now
        await advance_run(
            session,
            run,
            "cancelled",
            {"round": current.number, "reason": "confirmed_evidence_changed"},
        )


async def clean_terminal_jobs(sessions, settings, children, adapters, env_model, isolated):
    terminal = {child.id: child for child in children if child.state in TERMINAL}
    if not terminal:
        return False
    async with sessions() as session:
        owners = list(
            await session.scalars(
                select(CapacityLease.owner_id).where(
                    CapacityLease.owner_id.in_(terminal), CapacityLease.released.is_(False)
                )
            )
        )
    pending = False
    for owner in owners:
        child = terminal[owner]
        if isolated:
            await reclaim_child(sessions, settings, owner, model=env_model)
            async with sessions() as session:
                environment = await session.get(env_model, owner)
                pending |= environment is None or environment.state != "cleaned"
            continue
        job = JobRef(external_job_id=str(owner), submission_key=str(owner))
        cleanup = await adapters[child.id].cleanup(job)
        if cleanup.get("cleaned") is not True:
            pending = True
            if not (child.summary or {}).get("cleanup_pending"):
                child.summary = {
                    **(child.summary or {}),
                    "cleanup_pending": True,
                    "cleanup_reason": "remote_cleanup_unconfirmed",
                }
                await update_child(sessions, child, summary=child.summary)
            continue
        summary = dict(child.summary or {})
        summary.pop("cleanup_pending", None)
        summary.pop("cleanup_reason", None)
        async with sessions() as session, session.begin():
            stored = await session.get_one(type(child), owner, with_for_update=True)
            stored.summary = summary or None
            await release(session, owner)
        child.summary = summary or None
    return pending


def gpqa_report_summary(summary, unified, task):
    native = (unified.get("summary") or {}).get("datasets", [])
    accuracy = native[0].get("raw_accuracy") if len(native) == 1 else None
    scores = [c.get("score") for c in unified.get("cases", [])]
    complete = summary.get("validity") == "complete"
    verified = (
        complete
        and bool(scores)
        and all(type(v) in (int, float) and v in (0, 1) for v in scores)
        and type(accuracy) in (int, float)
        and 0 <= accuracy <= 100
        and abs(accuracy - sum(scores) / len(scores) * 100) < 0.0001
    )
    return {
        **summary,
        "expected_samples": summary.get("expected_cases", len(task["samples"])),
        "executed_attempts": summary.get("attempt_count", 0),
        "successful_samples": summary.get("observed_cases", 0) - summary.get("failed_cases", 0),
        "failed_samples": summary.get("failed_cases", 0),
        "missing_samples": summary.get("missing_cases", 0),
        "accuracy": accuracy if verified else None,
        "scoring_status": "succeeded" if verified else "failed",
        "subset_scope": task.get("subset_scope", "lite"),
        "dataset_samples": task.get("dataset_samples"),
        "metric_scope": "selected_manifest",
        "metric_conversion": "verified_native_accuracy" if verified else "not_verified",
    }


async def finish(sessions, settings, run_id, frozen, children, cancelled):
    from autoeval.evaluation.models import EvaluationReport

    async with sessions() as session, session.begin():
        run = await session.get(EvaluationRun, run_id, with_for_update=True)
        result = {
            "schema_version": "planned-report.v1",
            "run_id": str(run_id),
            "estimate": frozen.get("estimate"),
            "datasets": [child_view(c) for c in children],
            "actual_duration_sec": (
                max(c.finished_at for c in children if c.finished_at)
                - min(c.started_at for c in children if c.started_at)
            ).total_seconds()
            if any(c.started_at for c in children)
            else None,
            "gate_status": "not_applicable",
            "execution_origin": frozen["execution_origin"],
        }
        single_gpqa = (
            len(children) == 1
            and children[0].payload["dataset"] == "GPQA"
            and "parameters" in frozen
        )
        if single_gpqa:
            result.update(
                snapshot_sha256=digest(frozen),
                summary=children[0].summary or {},
                validity="complete"
                if children[0].state == "succeeded"
                and (children[0].summary or {}).get("scoring_status") == "succeeded"
                else "partial",
            )
        key = f"planned-reports/{run_id}/{digest(result)}.json"
        await asyncio.to_thread(write_manifest, settings, key, canonical_manifest(result))
        session.add(
            PlanningArtifact(
                kind="run_report", sha256=digest(result), object_key=key, payload=result
            )
        )
        if single_gpqa:
            session.add(
                EvaluationReport(
                    run_id=run_id,
                    validity=result["validity"],
                    snapshot_sha256=digest(frozen),
                    summary=result["summary"],
                    object_key=key,
                    sha256=digest(result),
                    execution_origin=frozen["execution_origin"],
                )
            )
        state = (
            "cancelled"
            if cancelled
            else "completed"
            if all(c.state == "succeeded" for c in children)
            else "failed"
        )
        await advance_run(session, run, state, {"report_object_key": key})
        if not single_gpqa:
            await session.flush()
            from autoeval.reporting.task_reports import publish_task_report

            await publish_task_report(session, settings, run_id)


def child_view(child):
    return {
        "id": str(child.id),
        "task_id": child.task_id,
        "dataset": child.payload["dataset"],
        "state": child.state,
        "summary": child.summary,
        "started_at": child.started_at.isoformat() if child.started_at else None,
        "finished_at": child.finished_at.isoformat() if child.finished_at else None,
        "actual_duration_sec": (child.finished_at - child.started_at).total_seconds()
        if child.started_at and child.finished_at
        else None,
    }


@activity.defn
async def execute_planned_evaluation(run_id: str, round_id: str | None = None):
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        # Prevent duplicate activity deliveries from controlling the same run concurrently.
        async with engine.connect() as connection:
            key = "execute:" + run_id
            owned = await connection.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key}
            )
            if not owned:
                raise RuntimeError("Run is already controlled")
            try:
                identifier = uuid.UUID(run_id)
                round_identifier = uuid.UUID(round_id) if round_id else None
                async with sessions() as session:
                    current = await session.scalar(
                        select(ExecutionRound.id)
                        .where(ExecutionRound.run_id == identifier)
                        .order_by(ExecutionRound.number.desc())
                        .limit(1)
                    )
                if current != round_identifier:
                    return
                await execute(
                    sessions,
                    settings,
                    identifier,
                    lambda: activity.heartbeat(run_id),
                    round_id=round_identifier,
                )
            finally:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key}
                )
    finally:
        await engine.dispose()
