import asyncio
import subprocess
import uuid

from sqlalchemy import select
from temporalio import activity

from autoeval.config import get_settings
from autoeval.contracts import JobRef
from autoeval.db import create_database
from autoeval.docker_executor import DockerExecutor
from autoeval.domain import RunState, check_transition
from autoeval.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.runs import DiagnosticResult, ExecutionLease, complete_cleanup


async def transition(sessions, run_id, state):
    async with sessions() as session, session.begin():
        row = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        if row.state != state:
            check_transition(RunState(row.state), RunState(state))
            row.state = state
            row.projection_version += 1
            session.add(RunEvent(run_id=run_id, seq=row.projection_version, type=state, body={}))


async def record_unresolved(sessions, run_id):
    async with sessions() as session, session.begin():
        row = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        if row is None or row.state in {"completed", "failed", "cancelled"}:
            return
        row.projection_version += 1
        session.add(
            RunEvent(
                run_id=run_id,
                seq=row.projection_version,
                type="execution_unresolved",
                body={"cleanup_pending": True, "ownership_retained": True},
            )
        )


@activity.defn
async def execute_docker_diagnostic(run_id: str):
    identifier = uuid.UUID(run_id)
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session:
            snapshot = await session.scalar(
                select(RunSnapshot).where(RunSnapshot.run_id == identifier)
            )
            frozen = snapshot.canonical_body
        adapter = DockerExecutor(
            settings.docker_executable, frozen["container_id"], frozen["image_id"]
        )
        job = JobRef(external_job_id=run_id, submission_key=run_id)

        async def cleanup_terminal():
            cleanup = await adapter.cleanup(job)
            if not cleanup.get("cleaned"):
                await record_unresolved(sessions, identifier)
                return {"state": "unresolved", "cleanup_pending": True}
            async with sessions() as session, session.begin():
                row = await session.scalar(
                    select(EvaluationRun).where(EvaluationRun.id == identifier).with_for_update()
                )
                await complete_cleanup(
                    session, row, observed_state=cleanup.get("observed_state", row.state)
                )
                return {"state": row.state}

        async with sessions() as session:
            current = await session.get(EvaluationRun, identifier)
            current_state = current.state
            lease = await session.scalar(
                select(ExecutionLease).where(ExecutionLease.run_id == identifier)
            )
        if current_state in {"completed", "failed", "cancelled"}:
            if lease is None:
                return {"state": current_state}
            return await cleanup_terminal()
        await transition(sessions, identifier, "queued")
        await transition(sessions, identifier, "preparing")
        submitted = False
        async with sessions() as session:
            cancelled = (
                await session.get(EvaluationRun, identifier)
            ).cancel_requested_at is not None
        if cancelled:
            await transition(sessions, identifier, "cancelling")
            state, summary = "cancelled", {"diagnostic_only": True, "model_called": False}
        else:
            job = await adapter.submit(
                {"kind": frozen["kind"], "duration_seconds": frozen["duration_seconds"]}, run_id
            )
            submitted = True
            await transition(sessions, identifier, "running")
            for _ in range(90):
                activity.heartbeat(run_id)
                async with sessions() as session:
                    cancelled = (
                        await session.get(EvaluationRun, identifier)
                    ).cancel_requested_at is not None
                if cancelled:
                    await transition(sessions, identifier, "cancelling")
                    observation = await adapter.cancel(job, "cancel:" + run_id)
                else:
                    observation = await adapter.status(job)
                if observation.state in {"succeeded", "failed", "cancelled"}:
                    state = "completed" if observation.state == "succeeded" else observation.state
                    summary = await adapter.collect(job)
                    if cancelled:
                        state = "cancelled"
                    elif state == "completed":
                        await transition(sessions, identifier, "aggregating")
                    break
                await asyncio.sleep(0.5)
            else:
                await record_unresolved(sessions, identifier)
                return {"state": "unresolved", "cleanup_pending": True}
        async with sessions() as session, session.begin():
            row = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == identifier).with_for_update()
            )
            check_transition(RunState(row.state), RunState(state))
            row.state = state
            row.projection_version += 1
            session.add(
                RunEvent(run_id=identifier, seq=row.projection_version, type=state, body={})
            )
            existing = await session.scalar(
                select(DiagnosticResult).where(DiagnosticResult.run_id == identifier)
            )
            if existing is None:
                session.add(
                    DiagnosticResult(
                        run_id=identifier, summary={**summary, "diagnostic_only": True}
                    )
                )
            if submitted:
                row.projection_version += 1
                session.add(
                    RunEvent(
                        run_id=identifier,
                        seq=row.projection_version,
                        type="execution_cleanup_pending",
                        body={"observed_state": state, "ownership_retained": True},
                    )
                )
            else:
                await complete_cleanup(session, row, observed_state="not_submitted")
        if submitted:
            return await cleanup_terminal()
        return {"state": state}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        # External submission may have succeeded. Retain ownership for reconciliation;
        # never release a lease or claim termination after a transport failure.
        await record_unresolved(sessions, identifier)
        return {"state": "unresolved", "cleanup_pending": True}
    finally:
        await engine.dispose()
