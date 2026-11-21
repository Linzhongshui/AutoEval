# ruff: noqa: PLC0414 -- explicit compatibility re-exports
"""Evaluation queries and compatibility exports."""

import asyncio

from fastapi import HTTPException
from sqlalchemy import select

from autoeval.catalog.datasets import read_manifest
from autoeval.evaluation.inputs import manifest_dataset_matches as manifest_dataset_matches
from autoeval.evaluation.inputs import resolve_inputs as resolve_inputs
from autoeval.evaluation.inputs import selection_identity as selection_identity
from autoeval.evaluation.inputs import target_data as target_data
from autoeval.evaluation.models import DatasetExecution, DatasetExecutionEnvironment
from autoeval.evaluation.resource_allocation import acquire as acquire
from autoeval.evaluation.resource_allocation import demand_for as demand_for
from autoeval.evaluation.resource_allocation import fits as fits
from autoeval.evaluation.resource_allocation import release as release
from autoeval.evaluation.submission import create_run as create_run
from autoeval.evaluation.submission import submit_planned_run as submit_planned_run
from autoeval.infrastructure.domain import RUN_TERMINAL
from autoeval.infrastructure.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.planning.artifacts import artifact as artifact
from autoeval.planning.artifacts import current_preflight as current_preflight


def child_environment_view(child, environment, hosts):
    template = environment.template if environment else child.payload.get("execution_template")
    if not template:
        return None
    resource_id = str(
        environment.resource_id if environment else child.payload["assigned_resource_id"]
    )
    return {
        "resource_id": resource_id,
        "host": hosts.get(resource_id),
        "tool": template["family"],
        "revision": template["revision"],
        "container_id": environment.container_id[:12]
        if environment and environment.container_id
        else None,
        "state": environment.state
        if environment
        else ("waiting_capacity" if child.state == "pending" else "not_created"),
    }


async def planned_run_detail(sessions, run_id):
    """Read one planned run with children and the archived report reference."""
    from autoeval.evaluation.models import EvaluationReport
    from autoeval.planning.models import PlanningArtifact

    async with sessions() as session:
        run = await session.get(EvaluationRun, run_id)
        if not run or run.trigger_scope != "local-operator:orchestration":
            raise HTTPException(404, "Planned run not found")
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        children = list(
            await session.scalars(select(DatasetExecution).where(DatasetExecution.run_id == run_id))
        )
        reports = list(
            await session.scalars(
                select(PlanningArtifact)
                .where(
                    PlanningArtifact.kind == "run_report",
                    PlanningArtifact.payload["run_id"].astext == str(run_id),
                )
                .limit(1)
            )
        )
        report_id = await session.scalar(
            select(EvaluationReport.id).where(EvaluationReport.run_id == run_id)
        )
        environments = {
            row.dataset_execution_id: row
            for row in await session.scalars(
                select(DatasetExecutionEnvironment).where(
                    DatasetExecutionEnvironment.dataset_execution_id.in_([c.id for c in children])
                )
            )
        }
        from autoeval.resources.models import SSHResourceBinding

        resource_ids = {row.resource_id for row in environments.values()}
        resource_ids.update(
            child.payload["assigned_resource_id"]
            for child in children
            if child.payload.get("execution_template")
        )
        hosts = {
            str(identifier): host
            for identifier, host in await session.execute(
                select(SSHResourceBinding.id, SSHResourceBinding.host).where(
                    SSHResourceBinding.id.in_(resource_ids)
                )
            )
        }
        from autoeval.evaluation.orchestration import child_view

        return {
            "report_id": str(report_id) if report_id else None,
            "id": str(run.id),
            "state": run.state,
            "estimate": snapshot.canonical_body.get("estimate"),
            "datasets": [
                {
                    **child_view(child),
                    "selected_cases": len(child.payload.get("samples", []))
                    if "samples" in child.payload
                    else None,
                    "execution_environment": child_environment_view(
                        child, environments.get(child.id), hosts
                    ),
                }
                for child in children
            ],
            "report": reports[0].payload if reports else None,
            "execution_origin": snapshot.canonical_body.get("execution_origin"),
        }


async def planned_run_report(sessions, settings, run_id):
    """Read the archived planned-run report evidence."""
    from autoeval.planning.models import PlanningArtifact

    async with sessions() as session:
        report = await session.scalar(
            select(PlanningArtifact)
            .where(
                PlanningArtifact.kind == "run_report",
                PlanningArtifact.payload["run_id"].astext == str(run_id),
            )
            .limit(1)
        )
        if report is None:
            raise HTTPException(404, "Report not available")
        try:
            return await asyncio.to_thread(read_manifest, settings, report)
        except ValueError as exc:
            raise HTTPException(503, "Report evidence integrity check failed") from exc


async def evaluation_run_detail(sessions, settings, run_id):
    """Read one evaluation run with events, snapshot, report and cleanup state."""
    from sqlalchemy.exc import SQLAlchemyError

    from autoeval.evaluation.models import EvaluationReport
    from autoeval.infrastructure.cleanup import ExecutionCleanup, cleanup_view

    try:
        async with sessions() as session:
            row = await session.get(EvaluationRun, run_id)
            if row is None or row.trigger_scope not in {
                "local-operator:evaluation",
                "local-operator:orchestration",
            }:
                raise HTTPException(404, "Evaluation run not found")
            events = (
                await session.scalars(
                    select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
                )
            ).all()
            report = await session.scalar(
                select(EvaluationReport).where(EvaluationReport.run_id == run_id)
            )
            cleanup = await session.scalar(
                select(ExecutionCleanup).where(ExecutionCleanup.run_id == run_id)
            )
            snapshot = await session.scalar(
                select(RunSnapshot).where(RunSnapshot.run_id == run_id)
            )
            return {
                "id": str(row.id),
                "state": row.state,
                "created_at": row.created_at.isoformat(),
                "updated_at": events[-1].created_at.isoformat()
                if events
                else row.created_at.isoformat(),
                "cancel_requested_at": row.cancel_requested_at.isoformat()
                if row.cancel_requested_at
                else None,
                "run_mode": row.run_mode,
                "snapshot": {
                    "sha256": snapshot.sha256,
                    **{
                        key: snapshot.canonical_body.get(key)
                        for key in (
                            "config_version_id",
                            "config_sha256",
                            "parameters",
                            "tool",
                            "profile_id",
                            "profile_sha256",
                            "max_model_requests",
                            "target_id",
                            "model_version_id",
                            "remote_model",
                            "resource_id",
                            "resource_kind",
                            "manifest_id",
                            "manifest_sha256",
                            "execution_origin",
                        )
                    },
                    # Planned runs freeze per-dataset samples instead of a top-level list.
                    "sample_count": len(snapshot.canonical_body.get("samples", []))
                    if snapshot.canonical_body.get("samples") is not None
                    else sum(
                        len(task.get("samples") or [])
                        for task in (snapshot.canonical_body.get("inputs") or {}).get(
                            "tasks", []
                        )
                    ),
                }
                if snapshot
                else None,
                "gate_status": "not_applicable",
                "cleanup": cleanup_view(
                    cleanup,
                    required=bool(
                        snapshot
                        and snapshot.canonical_body.get("resource_kind") == "customer_ssh"
                        and row.trigger_scope == "local-operator:evaluation"
                    ),
                ),
                "execution_unresolved": bool(
                    events and events[-1].type == "execution_unresolved"
                ),
                "events": [
                    {"seq": e.seq, "type": e.type, "created_at": e.created_at.isoformat()}
                    for e in events
                ],
                "report": {
                    "id": str(report.id),
                    "validity": report.validity,
                    "summary": report.summary,
                    "sha256": report.sha256,
                }
                if report
                else None,
            }
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Run database unavailable") from exc


async def evaluation_run_report(sessions, settings, run_id):
    """Read the archived evaluation report evidence from object storage."""
    from botocore.exceptions import BotoCoreError, ClientError
    from sqlalchemy.exc import SQLAlchemyError

    from autoeval.evaluation.models import EvaluationReport

    try:
        async with sessions() as session:
            report = await session.scalar(
                select(EvaluationReport).where(EvaluationReport.run_id == run_id)
            )
            if report is None:
                raise HTTPException(404, "Report not available")
            return await asyncio.to_thread(read_manifest, settings, report)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Report database unavailable") from exc
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise HTTPException(
            503, "Report evidence unavailable or integrity check failed"
        ) from exc


async def evaluation_retry_cleanup(sessions, settings, run_id):
    """Schedule resource reclamation for a terminal SSH run from this origin."""
    from autoeval.infrastructure.cleanup import schedule_cleanup

    async with sessions() as session, session.begin():
        row = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        if row is None or row.trigger_scope != "local-operator:evaluation":
            raise HTTPException(404, "Evaluation run not found")
        if (
            row.state not in RUN_TERMINAL
            or snapshot is None
            or snapshot.canonical_body.get("resource_kind") != "customer_ssh"
            or snapshot.canonical_body.get("execution_origin") != settings.evaluation_origin
        ):
            raise HTTPException(
                409, "Only terminal SSH runs from this execution origin may be reclaimed"
            )
        cleanup = await schedule_cleanup(session, run_id)
        if cleanup.state != "cleaned":
            cleanup.next_retry_at = None
        return {"accepted": True}
