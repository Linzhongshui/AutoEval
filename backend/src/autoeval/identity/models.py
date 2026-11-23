"""Identity ORM models: OAuth users, single-use authorize states, server-side sessions."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.infrastructure.models import Base, Record


class PlatformUser(Record, Base):
    __tablename__ = "platform_user"
    provider: Mapped[str] = mapped_column(String(16))
    provider_uid: Mapped[str] = mapped_column(String(64))
    login: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256))
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16), server_default="regular")
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("provider", "provider_uid", name="uq_platform_user_provider_uid"),
        CheckConstraint("provider IN ('github','gitcode')", name="ck_platform_user_provider"),
        CheckConstraint("role IN ('admin','regular')", name="ck_platform_user_role"),
    )


class OAuthState(Base):
    """One-time CSRF anchor consumed atomically on callback; never reused."""

    __tablename__ = "oauth_state"
    token: Mapped[str] = mapped_column(String(96), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("provider IN ('github','gitcode')", name="ck_oauth_state_provider"),
    )


class UserSession(Record, Base):
    __tablename__ = "user_session"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform_user.id", ondelete="RESTRICT"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
