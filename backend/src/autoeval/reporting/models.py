"""Reporting ORM models: case executions, unified collections/artifacts, workbench records."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.infrastructure.models import Base, Record


class CaseExecutionRecord(Record, Base):
    __tablename__ = "case_execution_record"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id", ondelete="RESTRICT"))
    dataset_key: Mapped[str] = mapped_column(String(128))
    sample_id: Mapped[str] = mapped_column(String(256))
    attempt_no: Mapped[int]
    operation_key: Mapped[str] = mapped_column(String(256))
    state: Mapped[str] = mapped_column(String(16))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    object_key: Mapped[str | None] = mapped_column(String(256))
    sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    tool_metadata: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("run_id", "operation_key"),
        UniqueConstraint("run_id", "dataset_key", "sample_id", "attempt_no"),
        CheckConstraint("attempt_no > 0"),
        CheckConstraint("state IN ('started','succeeded','failed')"),
        CheckConstraint(
            "(state = 'started' AND finished_at IS NULL AND object_key IS NULL AND sha256 IS NULL) OR (state <> 'started' AND finished_at IS NOT NULL AND object_key IS NOT NULL AND sha256 IS NOT NULL)"
        ),
        Index("ix_case_history_run_sample", "run_id", "dataset_key", "sample_id", "attempt_no"),
    )


class UnifiedCollection(Record, Base):
    __tablename__ = "unified_result_collection"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id", ondelete="RESTRICT"))
    collection_key: Mapped[str] = mapped_column(String(128))
    object_key: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("run_id", "collection_key"),)


class UnifiedArtifact(Record, Base):
    __tablename__ = "unified_output_artifact"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id", ondelete="RESTRICT"))
    collection_key: Mapped[str] = mapped_column(String(128))
    object_key: Mapped[str] = mapped_column(String(256))
    sha256: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("run_id", "collection_key"),)


class LeaderboardRecord(Record, Base):
    __tablename__ = "leaderboard_record"
    source_key: Mapped[str] = mapped_column(String(128), unique=True)
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evaluation_report.id"))
    state: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        CheckConstraint("state IN ('draft','approved','rejected','withdrawn')"),
        CheckConstraint("revision > 0"),
        Index("ix_leaderboard_record_state", "state", "created_at", "id"),
    )
