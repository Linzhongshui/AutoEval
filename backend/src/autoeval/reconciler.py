"""Recover diagnostic projections only after their Workflow has closed."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from autoeval.audit import record_audit
from autoeval.case_history import CaseExecutionRecord
from autoeval.config import get_settings
from autoeval.contracts import JobRef
from autoeval.db import create_database
from autoeval.docker_executor import DockerExecutor
from autoeval.domain import RunState, check_transition
from autoeval.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.runs import DiagnosticResult, ExecutionLease, complete_cleanup
from autoeval.workflows import GpqaExplorationWorkflow

log = logging.getLogger(__name__)


async def record_unresolved_once(session, row, *, reason: str, observed_state: str | None = None):
    latest = await session.scalar(
        select(RunEvent)
        .where(RunEvent.run_id == row.id)
        .order_by(RunEvent.seq.desc())
        .limit(1)
    )
    if latest is not None and latest.type == "execution_unresolved":
        return
    row.projection_version += 1
    details = {
        "reason": reason,
        "observed_state": observed_state,
        "cleanup_pending": True,
        "ownership_retained": True,
    }
    session.add(
        RunEvent(
            run_id=row.id,
            seq=row.projection_version,
            type="execution_unresolved",
            body={**details, "reconciled": True},
        )
    )
    record_audit(
        session,
        action="recovery.unresolved",
        resource_id=str(row.id),
        run_id=row.id,
        outcome="unresolved",
        request_id=f"reconcile:{row.id}",
        details=details,
    )


async def reconcile_diagnostic(sessions, client, settings, run_id):
    # An active Workflow owns all state writes. Never race its activity or resubmit.
    description = await client.get_workflow_handle(f"demo/run/{run_id}").describe()
    if description.status == WorkflowExecutionStatus.RUNNING:
        return "workflow_active"
    async with sessions() as session, session.begin():
        row = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        if row is None or row.trigger_scope != "local-operator:diagnostic":
            return "unsupported"
        lease = await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == run_id))
        if row.state in {"completed", "failed", "cancelled"} and lease is None:
            return "terminal"
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        frozen = snapshot.canonical_body
        adapter = DockerExecutor(
            settings.docker_executable, frozen["container_id"], frozen["image_id"]
        )
        job = JobRef(external_job_id=str(run_id), submission_key=str(run_id))
        observed_state = row.state
        if row.state not in {"completed", "failed", "cancelled"}:
            observation = await adapter.lookup(str(run_id))
            if row.cancel_requested_at and observation.state == "running":
                observation = await adapter.cancel(job, "reconcile-cancel:" + str(run_id))
            if observation.state not in {"succeeded", "failed", "cancelled"}:
                await record_unresolved_once(
                    session, row, reason="observation_nonterminal", observed_state=observation.state
                )
                return "unresolved"
            observed_state = observation.state
            summary = await adapter.collect(job)
            # Resolve missing projections from observed execution, never replay submit.
            if row.cancel_requested_at or observation.state == "cancelled":
                path = ["cancelling", "cancelled"]
            elif observation.state == "failed":
                if row.state == "cancelling":
                    path = ["cancelled"]
                else:
                    path = ["failed"]
            else:
                sequence = [
                    "accepted", "queued", "preparing", "running", "aggregating", "completed"
                ]
                if row.state == "cancelling":
                    path = ["cancelled"]
                else:
                    path = sequence[sequence.index(row.state) + 1 :]
            for state in path:
                if row.state == state:
                    continue
                check_transition(RunState(row.state), RunState(state))
                row.state = state
                row.projection_version += 1
                session.add(
                    RunEvent(
                        run_id=run_id,
                        seq=row.projection_version,
                        type=state,
                        body={"reconciled": True, "observed_state": observation.state},
                    )
                )
            session.add(
                DiagnosticResult(
                    run_id=run_id,
                    summary={**summary, "diagnostic_only": True, "reconciled": True},
                )
            )
            row.projection_version += 1
            session.add(
                RunEvent(
                    run_id=run_id,
                    seq=row.projection_version,
                    type="execution_cleanup_pending",
                    body={"observed_state": observed_state, "ownership_retained": True},
                )
            )
    cleanup = await adapter.cleanup(job)
    async with sessions() as session, session.begin():
        row = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        if not cleanup.get("cleaned"):
            await record_unresolved_once(
                session,
                row,
                reason="cleanup_nonterminal",
                observed_state=cleanup.get("state", "unknown"),
            )
            return "cleanup_unresolved"
        await complete_cleanup(
            session, row, observed_state=cleanup.get("observed_state", observed_state)
        )
        return row.state


async def reconcile_gpqa(sessions, client, settings, run_id):
    # The original Workflow exclusively owns writes and model submission while active.
    description = await client.get_workflow_handle(f"demo/run/{run_id}").describe()
    if description.status == WorkflowExecutionStatus.RUNNING:
        return "workflow_active"
    async with sessions() as session, session.begin():
        row = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        if row is None or row.trigger_scope != "local-operator:evaluation":
            return "unsupported"
        if row.state in {"completed", "failed", "cancelled"}:
            return "terminal"
        started = await session.scalar(
            select(CaseExecutionRecord.id)
            .where(
                CaseExecutionRecord.run_id == run_id,
                CaseExecutionRecord.state == "started",
            )
            .limit(1)
        )
        if started is not None:
            snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
            if snapshot.canonical_body.get("resource_kind") != "customer_ssh":
                await record_unresolved_once(session, row, reason="started_attempt")
                return "unresolved"
    recovery_id = f"demo/recovery/gpqa/{run_id}"
    try:
        recovery = await client.get_workflow_handle(recovery_id).describe()
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
    else:
        if recovery.status == WorkflowExecutionStatus.RUNNING:
            return "recovery_active"
    try:
        await client.start_workflow(
            GpqaExplorationWorkflow.run,
            {
                "run_id": str(run_id),
                "activity_queue": settings.gpqa_activity_queue,
                "resume": True,
            },
            id=recovery_id,
            task_queue=settings.gpqa_workflow_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        return "recovery_active"
    return "recovery_started"


async def reconcile_run(sessions, client, settings, run_id):
    async with sessions() as session:
        scope = await session.scalar(
            select(EvaluationRun.trigger_scope).where(EvaluationRun.id == run_id)
        )
    if scope == "local-operator:evaluation":
        return await reconcile_gpqa(sessions, client, settings, run_id)
    return await reconcile_diagnostic(sessions, client, settings, run_id)


async def serve():
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        client = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        while True:
            from autoeval.cleanup import ExecutionCleanup, reclaim

            async with sessions() as session:
                cleanup_ids = list(await session.scalars(
                    select(ExecutionCleanup.run_id)
                    .join(RunSnapshot, RunSnapshot.run_id == ExecutionCleanup.run_id)
                    .where(
                        ExecutionCleanup.state != "cleaned",
                        RunSnapshot.canonical_body["execution_origin"].astext == settings.evaluation_origin,
                        or_(ExecutionCleanup.next_retry_at.is_(None), ExecutionCleanup.next_retry_at <= datetime.now(UTC)),
                        or_(ExecutionCleanup.claimed_until.is_(None), ExecutionCleanup.claimed_until <= datetime.now(UTC)),
                    ).order_by(ExecutionCleanup.created_at).limit(100)
                ))
            for cleanup_id in cleanup_ids:
                try:
                    await reclaim(sessions, settings, cleanup_id)
                except Exception:  # noqa: BLE001 -- isolate failed reconciliation
                    log.warning("Cleanup deferred run=%s", cleanup_id)
            async with sessions() as session:
                ids = await session.scalars(
                    select(EvaluationRun.id)
                    .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
                    .outerjoin(ExecutionLease, ExecutionLease.run_id == EvaluationRun.id)
                    .where(
                        or_(EvaluationRun.trigger_scope == "local-operator:diagnostic",
                            and_(EvaluationRun.trigger_scope == "local-operator:evaluation",
                                 RunSnapshot.canonical_body["execution_origin"].astext == settings.evaluation_origin)),
                        or_(
                            EvaluationRun.state.not_in(["completed", "cancelled", "failed"]),
                            and_(
                                EvaluationRun.trigger_scope == "local-operator:diagnostic",
                                ExecutionLease.run_id.is_not(None),
                            ),
                        ),
                        EvaluationRun.created_at < datetime.now(UTC) - timedelta(minutes=5),
                    )
                    .limit(100)
                )
                for run_id in ids:
                    try:
                        result = await reconcile_run(sessions, client, settings, run_id)
                        log.info("Reconciliation run=%s result=%s", run_id, result)
                    except Exception:  # noqa: BLE001 -- isolate unavailable external systems; retain lease
                        log.warning("Reconciliation deferred run=%s", run_id)
            await asyncio.sleep(60)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
