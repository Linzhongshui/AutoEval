"""Evaluation ORM models; table names, columns and constraints stay unchanged."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.models import Base, Record


class EvaluationReport(Record, Base):
    __tablename__ = "evaluation_report"
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_run.id", ondelete="RESTRICT"), unique=True
    )
    validity: Mapped[str] = mapped_column(String(24))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict] = mapped_column(JSONB)
    object_key: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    execution_origin: Mapped[str] = mapped_column(String(16), server_default="unverified")
    __table_args__ = (
        CheckConstraint(
            "execution_origin IN ('real','simulation','unverified')",
            name="ck_report_origin",
        ),
    )


class ResultArchiveRevision(Record, Base):
    """Append-only interpretation of existing output, never a new execution attempt."""

    __tablename__ = "result_archive_revision"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id"))
    dataset_key: Mapped[str] = mapped_column(String(128))
    parent_collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("unified_result_collection.id")
    )
    object_key: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[dict] = mapped_column(JSONB)
    summary: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("run_id", "dataset_key", "sha256"),)


class DatasetExecution(Record, Base):
    __tablename__ = "dataset_execution"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id"))
    task_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    payload: Mapped[dict] = mapped_column(JSONB)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("run_id", "task_id"),)


class CapacityLease(Record, Base):
    __tablename__ = "planning_capacity_lease"
    owner_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    node_id: Mapped[str] = mapped_column(String(128), index=True)
    demand: Mapped[dict] = mapped_column(JSONB)
    released: Mapped[bool] = mapped_column(default=False)
