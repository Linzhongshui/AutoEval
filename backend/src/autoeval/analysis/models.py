"""Analysis ORM models: one immutable analysis job per report."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.models import Base, Record


class ReportAnalysis(Record, Base):
    __tablename__ = "report_analysis"
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_report.id", ondelete="RESTRICT"), unique=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(16), server_default="queued")
    retry_history: Mapped[list] = mapped_column(JSONB, server_default="[]")
    trigger: Mapped[str] = mapped_column(String(24))
    retry_count: Mapped[int] = mapped_column(server_default="0")
    report_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    baseline_comparison_sha256: Mapped[str | None] = mapped_column(String(64))
    baseline_comparison: Mapped[dict | None] = mapped_column(JSONB)
    target_snapshot: Mapped[dict] = mapped_column(JSONB)
    evidence_catalog: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    input_object_key: Mapped[str | None] = mapped_column(String(256))
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    object_key: Mapped[str | None] = mapped_column(String(256))
    sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    usage: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("state IN ('queued','running','succeeded','failed','unresolved')"),
        CheckConstraint("trigger IN ('report_created','manual_start','manual_retry')"),
        CheckConstraint("retry_count >= 0"),
        CheckConstraint("report_sha256 ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'"),
    )
