"""Read-only immutable report catalog, separate from prototype report data."""

import asyncio
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.datasets import read_manifest
from autoeval.evaluations import EvaluationReport
from autoeval.models import EvaluationRun, RunSnapshot

router = APIRouter(prefix="/api/autoeval/v1/reports", tags=["reports"])


def report_data(row, run, snapshot):
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "created_at": row.created_at.isoformat(),
        "validity": row.validity,
        "summary": row.summary,
        "sha256": row.sha256,
        "snapshot_sha256": row.snapshot_sha256,
        "run_mode": run.run_mode,
        "remote_model": snapshot.canonical_body["remote_model"],
        "config_version_id": snapshot.canonical_body["config_version_id"],
        "manifest_id": snapshot.canonical_body["manifest_id"],
        "execution_origin": row.execution_origin,
        "gate_status": "not_applicable",
        "analysis_status": "not_enabled",
    }


@router.get("")
async def catalog(request: Request, offset: int = 0, limit: int = 20):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    try:
        async with request.app.state.sessions() as session:
            rows = (
                await session.execute(
                    select(EvaluationReport, EvaluationRun, RunSnapshot)
                    .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
                    .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
                    .where(
                        EvaluationRun.trigger_scope == "local-operator:evaluation",
                        EvaluationReport.execution_origin == "real",
                    )
                    .order_by(EvaluationReport.created_at.desc(), EvaluationReport.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
            data = [report_data(*row) for row in rows[:limit]]
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Report catalog unavailable") from exc
    return {
        "data": data,
        "next_offset": offset + limit if len(rows) > limit else None,
        "request_id": request.state.request_id,
    }


@router.get("/{report_id}")
async def detail(report_id: uuid.UUID, request: Request):
    try:
        async with request.app.state.sessions() as session:
            row = (
                await session.execute(
                    select(EvaluationReport, EvaluationRun, RunSnapshot)
                    .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
                    .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
                    .where(
                        EvaluationReport.id == report_id,
                        EvaluationRun.trigger_scope == "local-operator:evaluation",
                        EvaluationReport.execution_origin == "real",
                    )
                )
            ).one_or_none()
            if row is None:
                raise HTTPException(404, "Report not found")
            data = report_data(*row)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Report database unavailable") from exc
    return {"data": data, "request_id": request.state.request_id}


@router.get("/{report_id}/evidence")
async def evidence(report_id: uuid.UUID, request: Request):
    try:
        async with request.app.state.sessions() as session:
            row = await session.scalar(
                select(EvaluationReport)
                .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
                .where(
                    EvaluationReport.id == report_id,
                    EvaluationRun.trigger_scope == "local-operator:evaluation",
                    EvaluationReport.execution_origin == "real",
                )
            )
            if row is None:
                raise HTTPException(404, "Report not found")
            data = await asyncio.to_thread(read_manifest, request.app.state.settings, row)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Report database unavailable") from exc
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise HTTPException(503, "Report evidence unavailable or integrity check failed") from exc
    return {"data": data, "request_id": request.state.request_id}
