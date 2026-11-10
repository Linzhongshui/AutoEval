"""Recover diagnostic projections only after their Workflow has closed."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from temporalio.client import Client, WorkflowExecutionStatus

from autoeval.config import get_settings
from autoeval.contracts import JobRef
from autoeval.db import create_database
from autoeval.docker_executor import DockerExecutor
from autoeval.domain import RunState, check_transition
from autoeval.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.runs import DiagnosticResult, ExecutionLease

log = logging.getLogger(__name__)


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
        if row.state in {"completed", "failed", "cancelled"}:
            return "terminal"
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        frozen = snapshot.canonical_body
        adapter = DockerExecutor(
            settings.docker_executable, frozen["container_id"], frozen["image_id"]
        )
        job = JobRef(external_job_id=str(run_id), submission_key=str(run_id))
        observation = await adapter.lookup(str(run_id))
        if row.cancel_requested_at and observation.state == "running":
            observation = await adapter.cancel(job, "reconcile-cancel:" + str(run_id))
        if observation.state not in {"succeeded", "failed", "cancelled"}:
            return "unresolved"
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
            sequence = ["accepted", "queued", "preparing", "running", "aggregating", "completed"]
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
                run_id=run_id, summary={**summary, "diagnostic_only": True, "reconciled": True}
            )
        )
        lease = await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == run_id))
        if lease is not None:
            await session.delete(lease)
        return row.state


async def serve():
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        client = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        while True:
            async with sessions() as session:
                ids = await session.scalars(
                    select(EvaluationRun.id)
                    .where(
                        EvaluationRun.state.not_in(["completed", "cancelled", "failed"]),
                        EvaluationRun.created_at < datetime.now(UTC) - timedelta(minutes=5),
                    )
                    .limit(100)
                )
                for run_id in ids:
                    try:
                        result = await reconcile_diagnostic(sessions, client, settings, run_id)
                        log.info("Reconciliation run=%s result=%s", run_id, result)
                    except Exception:  # noqa: BLE001 -- isolate unavailable external systems; retain lease
                        log.warning("Reconciliation deferred run=%s", run_id)
            await asyncio.sleep(60)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
