"""GPQA Lite exploration submission; Release validation remains unavailable."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.catalog.datasets import canonical_manifest
from autoeval.evaluation.models import EvaluationReport
from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
from autoeval.infrastructure.responses import Accepted, Envelope, PageEnvelope


class SubmitEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config_version_id: uuid.UUID
    target_id: uuid.UUID
    resource_id: uuid.UUID
    run_mode: Literal["exploration"]
    max_model_requests: int = Field(ge=1, le=5)
    resource_kind: Literal["docker_local", "customer_ssh"] = "docker_local"


class ExplorationSubmitted(BaseModel):
    run_id: str
    state: str
    expected_samples: int | None = None
    gate_status: str | None = None


class RunListItem(BaseModel):
    id: str
    state: str
    report_id: str | None
    created_at: str
    remote_model: str | None
    resource_kind: str | None = None


router = APIRouter(prefix="/api/autoeval/v1/runs", tags=["evaluation runs"])


@router.get("", response_model=PageEnvelope[RunListItem])
async def list_runs(request: Request, offset: int = 0, limit: int = 50):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    try:
        async with request.app.state.sessions() as session:
            rows = (
                await session.execute(
                    select(EvaluationRun, RunSnapshot, EvaluationReport.id)
                    .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
                    .outerjoin(EvaluationReport, (EvaluationReport.run_id == EvaluationRun.id) & EvaluationReport.is_current)
                    .where(
                        EvaluationRun.trigger_scope.in_(
                            ["local-operator:evaluation", "local-operator:orchestration"]
                        )
                    )
                    .where(
                        or_(
                            RunSnapshot.canonical_body["execution_origin"].astext
                            == request.app.state.settings.evaluation_origin,
                            EvaluationReport.execution_origin
                            == request.app.state.settings.evaluation_origin,
                        )
                    )
                    .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
            return {
                "data": [
                    {
                        "id": str(r.id),
                        "state": r.state,
                        "report_id": str(report_id) if report_id else None,
                        "created_at": r.created_at.isoformat(),
                        "remote_model": snapshot.canonical_body.get("remote_model"),
                        "resource_kind": snapshot.canonical_body.get(
                            "resource_kind", "docker_local"
                        ),
                    }
                    for r, snapshot, report_id in rows[:limit]
                ],
                "next_offset": offset + limit if len(rows) > limit else None,
                "request_id": request.state.request_id,
            }
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Run database unavailable") from exc


@router.post("", status_code=202, response_model=Envelope[ExplorationSubmitted])
async def submit(
    body: SubmitEvaluation,
    request: Request,
    idempotency_key: str = Header(min_length=1, max_length=256),
):
    # Preserve existing Docker idempotency hashes when the new selector is omitted.
    request_body = body.model_dump(
        mode="json", exclude={"resource_kind"} if body.resource_kind == "docker_local" else set()
    )
    digest = hashlib.sha256(canonical_manifest(request_body)).hexdigest()
    from autoeval.evaluation.submission import replay_legacy_submission

    return await replay_legacy_submission(request, idempotency_key, digest)


@router.get("/{run_id}", response_model=Envelope[dict])
async def detail(run_id: uuid.UUID, request: Request):
    # Deferred: keeps module import free of the standard-inputs/data-workbench cycle.
    from autoeval.evaluation.service import evaluation_run_detail

    data = await evaluation_run_detail(
        request.app.state.sessions, request.app.state.settings, run_id
    )
    return {"data": data, "request_id": request.state.request_id}


@router.post("/{run_id}/cleanup", status_code=202, response_model=Envelope[Accepted])
async def retry_cleanup(run_id: uuid.UUID, request: Request):
    from autoeval.evaluation.service import evaluation_retry_cleanup

    data = await evaluation_retry_cleanup(
        request.app.state.sessions, request.app.state.settings, run_id
    )
    return {"data": data, "request_id": request.state.request_id}


@router.post("/{run_id}/cancel", status_code=202, response_model=Envelope[Accepted])
async def cancel(run_id: uuid.UUID, request: Request):
    try:
        async with request.app.state.sessions() as session, session.begin():
            row = await session.scalar(
                select(EvaluationRun)
                .where(
                    EvaluationRun.id == run_id,
                    EvaluationRun.trigger_scope.in_(["local-operator:evaluation", "local-operator:orchestration"])
                    if request.app.state.settings.environment not in {"development", "test"}
                    else EvaluationRun.trigger_scope.in_(
                        [
                            "local-operator:evaluation",
                            "local-operator:orchestration",
                            "local-operator:unified-fixture",
                        ]
                    ),
                )
                .with_for_update()
            )
            if row is None:
                raise HTTPException(404, "Evaluation run not found")
            accepted = row.state not in {"completed", "failed", "cancelled"}
            if accepted:
                row.cancel_requested_at = datetime.now(UTC)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Run database unavailable") from exc
    return {"data": {"accepted": accepted}, "request_id": request.state.request_id}


@router.get("/{run_id}/report", response_model=Envelope[dict])
async def report_evidence(run_id: uuid.UUID, request: Request):
    from autoeval.evaluation.service import evaluation_run_report

    data = await evaluation_run_report(
        request.app.state.sessions, request.app.state.settings, run_id
    )
    return {"data": data, "request_id": request.state.request_id}
