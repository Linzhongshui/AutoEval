"""Evaluation ORM models."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.infrastructure.models import Base, Record


class EvaluationReport(Record, Base):
    __tablename__ = "evaluation_report"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(server_default="1")
    is_current: Mapped[bool] = mapped_column(server_default=text("true"))
    validity: Mapped[str] = mapped_column(String(24))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict] = mapped_column(JSONB)
    object_key: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    execution_origin: Mapped[str] = mapped_column(String(16), server_default="unverified")
    review_status: Mapped[str] = mapped_column(
        String(16), server_default="pending", default="pending"
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(256))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(1000))
    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_evaluation_report_run_version"),
        Index(
            "uq_evaluation_report_current",
            "run_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint(
            "execution_origin IN ('real','simulation','unverified')",
            name="ck_report_origin",
        ),
        CheckConstraint(
            "review_status IN ('pending','approved','revoked')",
            name="ck_evaluation_report_review_status",
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


class DatasetExecutionEnvironment(Base):
    __tablename__ = "dataset_execution_environment"

    dataset_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_execution.id"), primary_key=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ssh_resource_binding.id"))
    template: Mapped[dict] = mapped_column(JSONB)
    container_id: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), index=True)

    cleanup_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionRound(Record, Base):
    __tablename__ = "evaluation_execution_round"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id", ondelete="RESTRICT"))
    number: Mapped[int]
    source_number: Mapped[int]
    operation: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(256))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    scope_sha256: Mapped[str] = mapped_column(String(64))
    selection: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(24), server_default="queued")
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("run_id", "number"),
        UniqueConstraint("run_id", "source_number"),
        CheckConstraint("source_number >= 1 AND number = source_number + 1"),
        CheckConstraint("operation IN ('resume', 'case_retry')"),
    )


class RoundRequest(Record, Base):
    __tablename__ = "evaluation_round_request"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id"))
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_execution_round.id"))
    idempotency_key: Mapped[str] = mapped_column(String(256))
    request_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"),)


class ExecutionShard(Record, Base):
    __tablename__ = "evaluation_execution_shard"
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_execution_round.id"))
    task_id: Mapped[str] = mapped_column(String(64))
    position: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(24), server_default="pending")
    summary: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("round_id", "position"),
        CheckConstraint("position >= 0"),
    )


class ExecutionShardEnvironment(Base):
    __tablename__ = "execution_shard_environment"

    shard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_execution_shard.id"), primary_key=True
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ssh_resource_binding.id"))
    template: Mapped[dict] = mapped_column(JSONB)
    container_id: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), index=True)
    cleanup_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
