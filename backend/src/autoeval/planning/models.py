"""Planning ORM models; table names, columns and constraints stay unchanged."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.models import Base, Record


class PlanningArtifact(Record, Base):
    __tablename__ = "planning_artifact"
    kind: Mapped[str] = mapped_column(String(24))
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(256))
    payload: Mapped[dict] = mapped_column(JSONB)


class PlanningJob(Record, Base):
    __tablename__ = "planning_job"
    kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    payload: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    # Worker uses a session advisory lock; running jobs may be resumed after worker death.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
