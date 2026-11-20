"""Read-only immutable report catalog, separate from prototype report data."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.analysis import ReportAnalysis, analysis_status_for
from autoeval.catalog.benchmarks import compare_baseline
from autoeval.catalog.datasets import read_manifest
from autoeval.catalog.models import BenchmarkBaseline
from autoeval.evaluation.models import EvaluationReport
from autoeval.infrastructure.audit import record_audit
from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
from autoeval.infrastructure.responses import Envelope, PageEnvelope
from autoeval.reporting.report_integrity import verified_report_body
from autoeval.reporting.report_view import report_data

router = APIRouter(prefix="/api/autoeval/v1/reports", tags=["reports"])


class ReportView(BaseModel):
    dataset_results: list[dict] | None = None
    id: str
    run_id: str
    execution_kind: str
    created_at: str
    validity: str
    evidence_status: str
    summary: dict
    dataset_key: str
    sha256: str
    snapshot_sha256: str
    run_mode: str | None
    remote_model: Any
    config_version_id: Any = None
    manifest_id: Any = None
    nomination_conditions: dict
    execution_origin: str
    gate_status: str
    analysis_status: str
    analysis_id: str | None
    baseline_comparison: dict
    review_status: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None


class ReviewInput(BaseModel):
    decision: Literal["approve", "revoke"]
    note: str | None = Field(default=None, max_length=1000)


@router.get("", response_model=PageEnvelope[ReportView])
async def catalog(
    request: Request,
    offset: int = 0,
    limit: int = 20,
    summary_only: bool = False,
    review_status: str | None = None,
):

    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    if review_status is not None and review_status not in {"pending", "approved", "revoked"}:
        raise HTTPException(422, "Invalid review status")

    try:
        async with request.app.state.sessions() as session:
            rows = (
                await session.execute(
                    select(EvaluationReport, EvaluationRun, RunSnapshot)
                    .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
                    .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
                    .where(
                        EvaluationRun.trigger_scope.in_(
                            ["local-operator:evaluation", "local-operator:orchestration"]
                        ),
                        EvaluationReport.execution_origin == "real",
                        *(
                            [EvaluationReport.review_status == review_status]
                            if review_status
                            else []
                        ),
                    )
                    .order_by(EvaluationReport.created_at.desc(), EvaluationReport.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()

            baselines = (await session.scalars(select(BenchmarkBaseline))).all()

            selected = rows[:limit]

            analyses = (
                (
                    await session.scalars(
                        select(ReportAnalysis).where(
                            ReportAnalysis.report_id.in_([row[0].id for row in selected])
                        )
                    )
                ).all()
                if selected
                else []
            )

            jobs = {job.report_id: job for job in analyses}

        semaphore = asyncio.Semaphore(8)

        async def check(row):
            async with semaphore:
                return await verified_report_body(request.app.state.settings, *row)

        evidence = await asyncio.gather(*(check(row) for row in selected))
        data = []
        for row, (status, body) in zip(selected, evidence, strict=True):
            job = jobs.get(row[0].id)
            item = report_data(
                *row,
                baselines,
                analysis_status=analysis_status_for(
                    job,
                    request.app.state.settings,
                    execution_origin=row[0].execution_origin,
                ),
                analysis_id=job.id if job else None,
                evidence_status=status,
            )
            attach_datasets(item, body, baselines, summary_only=summary_only)
            data.append(item)

    except SQLAlchemyError as exc:
        raise HTTPException(503, "Report catalog unavailable") from exc

    return {
        "data": data,
        "next_offset": offset + limit if len(rows) > limit else None,
        "request_id": request.state.request_id,
    }


@router.get("/{report_id}", response_model=Envelope[ReportView])
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
                        or_(
                            and_(
                                EvaluationRun.trigger_scope.in_(
                                    ["local-operator:evaluation", "local-operator:orchestration"]
                                ),
                                EvaluationReport.execution_origin == "real",
                            ),
                            and_(
                                EvaluationRun.trigger_scope == "local-operator:unified-fixture",
                                EvaluationReport.execution_origin == "simulation",
                                request.app.state.settings.environment in {"development", "test"},
                            ),
                        ),
                    )
                )
            ).one_or_none()

            if row is None:
                raise HTTPException(404, "Report not found")

            baselines = (await session.scalars(select(BenchmarkBaseline))).all()

            job = await session.scalar(
                select(ReportAnalysis).where(ReportAnalysis.report_id == report_id)
            )

            status, body = await verified_report_body(request.app.state.settings, *row)
            data = report_data(
                *row,
                baselines,
                analysis_status=analysis_status_for(
                    job,
                    request.app.state.settings,
                    execution_origin=row[0].execution_origin,
                ),
                analysis_id=job.id if job else None,
                evidence_status=status,
            )

            attach_datasets(data, body, baselines)

    except SQLAlchemyError as exc:
        raise HTTPException(503, "Report database unavailable") from exc

    return {"data": data, "request_id": request.state.request_id}


@router.post("/{report_id}/review", response_model=Envelope[dict])
async def review(report_id: uuid.UUID, body: ReviewInput, request: Request):
    """Mark one immutable report as an approved history source; never edits evidence."""
    if body.decision == "approve" and body.note is not None:
        body = body.model_copy(update={"note": body.note.strip() or None})
    try:
        async with request.app.state.sessions() as session, session.begin():
            row = await session.get(EvaluationReport, report_id, with_for_update=True)
            if row is None:
                raise HTTPException(404, "Report not found")
            run = await session.get(EvaluationRun, row.run_id)
            snapshot = await session.scalar(
                select(RunSnapshot).where(RunSnapshot.run_id == row.run_id)
            )
            if run is None or snapshot is None:
                raise HTTPException(409, "Report source is unavailable")
            previous = row.review_status
            if body.decision == "approve":
                if previous == "approved":
                    return {
                        "data": review_data(row),
                        "request_id": request.state.request_id,
                    }
                if (
                    row.execution_origin != "real"
                    or row.validity != "complete"
                    or run.state != "completed"
                ):
                    raise HTTPException(409, "Only complete real reports can be approved")
                status, _ = await verified_report_body(
                    request.app.state.settings, row, run, snapshot
                )
                if status != "verified":
                    raise HTTPException(409, "Report evidence is not verified")
                row.review_status = "approved"
                row.reviewed_by = "local-operator"
                row.reviewed_at = datetime.now(UTC)
                row.review_note = body.note
                action = "report.review.approve"
                outcome = "approved"
            else:
                if previous != "approved":
                    raise HTTPException(409, "Only approved reports can be revoked")
                row.review_status = "revoked"
                row.reviewed_by = "local-operator"
                row.reviewed_at = datetime.now(UTC)
                row.review_note = body.note
                action = "report.review.revoke"
                outcome = "revoked"
            record_audit(
                session,
                action=action,
                resource_id=str(row.id),
                run_id=row.run_id,
                outcome=outcome,
                request_id=request.state.request_id,
                details={"previous": previous, "note": body.note},
                resource_type="evaluation_report",
            )
            return {
                "data": review_data(row),
                "request_id": request.state.request_id,
            }
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Report review database unavailable") from exc


def review_data(row):
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "review_status": row.review_status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_note": row.review_note,
    }


@router.get("/{report_id}/evidence", response_model=Envelope[dict])
async def evidence(report_id: uuid.UUID, request: Request):

    try:
        async with request.app.state.sessions() as session:
            row = await session.scalar(
                select(EvaluationReport)
                .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
                .where(
                    EvaluationReport.id == report_id,
                    EvaluationRun.trigger_scope.in_(
                        ["local-operator:evaluation", "local-operator:orchestration"]
                    ),
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


def attach_datasets(data, body, baselines, *, summary_only=False):
    if body is None or body.get("schema_version") != "task-report.v2":
        return

    data["dataset_key"] = ", ".join(d["dataset_key"] for d in body["datasets"])
    if summary_only:
        return

    data["dataset_results"] = [
        {
            **d,
            "evidence_status": "verified" if d["archive"] else "missing",
            "baseline_comparison": compare_baseline(d["summary"], d["context"], baselines),
        }
        for d in body["datasets"]
    ]
