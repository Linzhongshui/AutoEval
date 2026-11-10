"""Persistent diagnostic tasks. This API does not submit model benchmarks."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.audit import record_audit
from autoeval.models import Base, EvaluationRun, Outbox, Record, RunEvent, RunSnapshot
from autoeval.resources import ResourceBinding


class ExecutionLease(Base):
    __tablename__ = "execution_lease"
    container_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_run.id", ondelete="RESTRICT"), unique=True
    )


class DiagnosticResult(Record, Base):
    __tablename__ = "diagnostic_result"
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_run.id", ondelete="RESTRICT"), unique=True
    )
    summary: Mapped[dict] = mapped_column(JSONB)


async def complete_cleanup(session, row, *, observed_state: str):
    lease = await session.scalar(select(ExecutionLease).where(ExecutionLease.run_id == row.id))
    if lease is None:
        return False
    details = {"observed_state": observed_state, "ownership_released": True}
    row.projection_version += 1
    session.add(
        RunEvent(
            run_id=row.id, seq=row.projection_version, type="execution_cleaned", body=details
        )
    )
    record_audit(
        session,
        action="execution.cleanup",
        resource_id=str(row.id),
        run_id=row.id,
        outcome="cleaned",
        request_id=f"cleanup:{row.id}",
        details=details,
    )
    await session.delete(lease)
    return True


class DiagnosticInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_binding_id: uuid.UUID
    kind: Literal["framework_smoke"]
    duration_seconds: int = Field(ge=0, le=30)


router = APIRouter(prefix="/api/autoeval/v1/diagnostics/runs", tags=["diagnostic tasks"])


@router.post("", status_code=202)
async def submit(
    body: DiagnosticInput,
    request: Request,
    idempotency_key: str = Header(min_length=1, max_length=256),
):
    payload = body.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    try:
        async with request.app.state.sessions() as session, session.begin():
            old = await session.scalar(
                select(EvaluationRun).where(
                    EvaluationRun.trigger_scope == "local-operator:diagnostic",
                    EvaluationRun.idempotency_key == idempotency_key,
                )
            )
            if old:
                if old.request_hash != digest:
                    raise HTTPException(409, "Idempotency content conflict")
                return {
                    "data": {"run_id": str(old.id), "state": old.state, "diagnostic_only": True},
                    "request_id": request.state.request_id,
                }
            binding = await session.get(ResourceBinding, body.resource_binding_id)
            if binding is None:
                raise HTTPException(404, "Resource binding not found")
            run = EvaluationRun(
                trigger_scope="local-operator:diagnostic",
                idempotency_key=idempotency_key,
                request_hash=digest,
                run_mode="exploration",
                created_by="local-operator",
            )
            session.add(run)
            await session.flush()
            session.add(ExecutionLease(container_id=binding.container_id, run_id=run.id))
            frozen = {**payload, "container_id": binding.container_id, "image_id": binding.image_id}
            session.add(
                RunSnapshot(
                    run_id=run.id,
                    schema_version="diagnostic.v1",
                    canonical_body=frozen,
                    sha256=hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest(),
                )
            )
            session.add(
                Outbox(
                    run_id=run.id,
                    kind="START_RUN",
                    dedup_key="start:" + str(run.id),
                    payload={"workflow_kind": "docker_diagnostic"},
                )
            )
            session.add(
                RunEvent(run_id=run.id, seq=1, type="accepted", body={"diagnostic_only": True})
            )
            record_audit(
                session, action="diagnostic.submit", resource_id=str(run.id), run_id=run.id,
                outcome="accepted", request_id=request.state.request_id,
                details={"diagnostic_only": True},
            )
            data = {"run_id": str(run.id), "state": "accepted", "diagnostic_only": True}
    except IntegrityError as exc:
        raise HTTPException(409, "Resource busy or concurrent request; retry same key") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Run database unavailable") from exc
    return {"data": data, "request_id": request.state.request_id}


@router.get("")
async def list_runs(request: Request):
    try:
        async with request.app.state.sessions() as session:
            rows = (
                await session.scalars(
                    select(EvaluationRun)
                    .where(EvaluationRun.trigger_scope == "local-operator:diagnostic")
                    .order_by(EvaluationRun.created_at.desc())
                    .limit(100)
                )
            ).all()
            data = [
                {"id": str(row.id), "state": row.state, "diagnostic_only": True} for row in rows
            ]
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Run database unavailable") from exc
    return {"data": data, "request_id": request.state.request_id}


@router.get("/{run_id}")
async def detail(run_id: uuid.UUID, request: Request):
    try:
        async with request.app.state.sessions() as session:
            row = await session.get(EvaluationRun, run_id)
            if row is None or row.trigger_scope != "local-operator:diagnostic":
                raise HTTPException(404, "Diagnostic task not found")
            result = await session.scalar(
                select(DiagnosticResult).where(DiagnosticResult.run_id == run_id)
            )
            events = (
                await session.scalars(
                    select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
                )
            ).all()
            ownership_held = await session.scalar(
                select(ExecutionLease.run_id).where(ExecutionLease.run_id == run_id)
            ) is not None
            unresolved = bool(events and events[-1].type == "execution_unresolved")
            cleanup_pending = any(event.type == "execution_cleanup_pending" for event in events) or (
                unresolved and events[-1].body.get("cleanup_pending", False)
            )
            data = {
                "id": str(run_id),
                "state": row.state,
                "diagnostic_only": True,
                "execution_unresolved": unresolved,
                "ownership_held": ownership_held,
                "cleanup_state": (
                    "completed"
                    if any(event.type == "execution_cleaned" for event in events)
                    else "pending"
                    if cleanup_pending
                    else "not_requested"
                ),
                "gate_status": "not_applicable",
                "result": result.summary if result else None,
                "events": [{"seq": e.seq, "type": e.type, "body": e.body} for e in events],
            }
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Run database unavailable") from exc
    return {"data": data, "request_id": request.state.request_id}


@router.post("/{run_id}/cancel", status_code=202)
async def cancel(run_id: uuid.UUID, request: Request):
    try:
        async with request.app.state.sessions() as session, session.begin():
            row = await session.scalar(
                select(EvaluationRun)
                .where(
                    EvaluationRun.id == run_id,
                    EvaluationRun.trigger_scope == "local-operator:diagnostic",
                )
                .with_for_update()
            )
            if row is None:
                raise HTTPException(404, "Diagnostic task not found")
            accepted = row.state not in {"completed", "cancelled", "failed"}
            if accepted:
                row.cancel_requested_at = datetime.now(UTC)
            record_audit(
                session, action="diagnostic.cancel", resource_id=str(row.id), run_id=row.id,
                outcome="accepted" if accepted else "unchanged",
                request_id=request.state.request_id, details={"accepted": accepted},
            )
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Run database unavailable") from exc
    return {"data": {"accepted": accepted}, "request_id": request.state.request_id}
