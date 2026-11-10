"""Append-only local-operator audit events with read-only pagination."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import ForeignKey, Index, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.models import Base, Record


class AuditEvent(Record, Base):
    __tablename__ = "audit_event"
    actor: Mapped[str] = mapped_column(String(256))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(128))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evaluation_run.id", ondelete="RESTRICT")
    )
    outcome: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        Index("ix_audit_event_resource", "resource_type", "resource_id", "created_at", "id"),
        Index("ix_audit_event_run", "run_id", "created_at", "id"),
    )


def record_audit(session, *, action: str, resource_id: str, run_id: uuid.UUID | None,
                 outcome: str, request_id: str, details: dict):
    session.add(AuditEvent(
        actor="local-operator", action=action, resource_type="evaluation_run",
        resource_id=resource_id, run_id=run_id, outcome=outcome,
        request_id=request_id, details=details,
    ))


router = APIRouter(prefix="/api/autoeval/v1/audit-events", tags=["audit"])


@router.get("")
async def list_audit_events(request: Request, offset: int = 0, limit: int = 100,
                            run_id: uuid.UUID | None = None, resource_id: str | None = None):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    try:
        async with request.app.state.sessions() as session:
            query = select(AuditEvent)
            if run_id is not None:
                query = query.where(AuditEvent.run_id == run_id)
            if resource_id is not None:
                query = query.where(AuditEvent.resource_id == resource_id)
            rows = (await session.scalars(
                query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                .offset(offset).limit(limit + 1)
            )).all()
            data = [{
                "id": str(row.id), "created_at": row.created_at.isoformat(),
                "actor": row.actor, "action": row.action,
                "resource_type": row.resource_type, "resource_id": row.resource_id,
                "run_id": str(row.run_id) if row.run_id else None,
                "outcome": row.outcome, "request_id": row.request_id, "details": row.details,
            } for row in rows[:limit]]
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Audit database unavailable or migration required") from exc
    return {
        "data": data,
        "next_offset": offset + limit if len(rows) > limit else None,
        "request_id": request.state.request_id,
    }
