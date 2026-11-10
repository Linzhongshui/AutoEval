import asyncio
import subprocess
import uuid

from sqlalchemy import delete, select
from temporalio import activity

from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.docker_executor import DockerExecutor
from autoeval.domain import RunState, check_transition
from autoeval.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.runs import DiagnosticResult, ExecutionLease


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
        await transition(sessions, identifier, "queued")
        await transition(sessions, identifier, "preparing")
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
            await session.execute(delete(ExecutionLease).where(ExecutionLease.run_id == identifier))
        return {"state": state}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        # External submission may have succeeded. Retain ownership for reconciliation;
        # never release a lease or claim termination after a transport failure.
        await record_unresolved(sessions, identifier)
        return {"state": "unresolved", "cleanup_pending": True}
    finally:
        await engine.dispose()
