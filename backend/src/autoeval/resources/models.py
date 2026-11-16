"""Resource ORM models: model-service targets, Docker executor and SSH bindings, probes."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.models import Base, Record


class TargetBinding(Record, Base):
    __tablename__ = "target_binding_version"
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset_version.id", ondelete="RESTRICT")
    )
    service_name: Mapped[str] = mapped_column(String(128), default="", server_default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    base_url: Mapped[str] = mapped_column(String(2048))
    remote_model: Mapped[str] = mapped_column(String(128))
    credential_ref: Mapped[str] = mapped_column(String(32))


class ConnectionProbe(Record, Base):
    __tablename__ = "connection_probe"
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("target_binding_version.id", ondelete="RESTRICT")
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSONB)


class ResourceProvider(Record, Base):
    __tablename__ = "resource_provider"
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))


class ResourceBinding(Record, Base):
    __tablename__ = "resource_binding_version"
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resource_provider.id", ondelete="RESTRICT")
    )
    binding_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    container_id: Mapped[str] = mapped_column(String(64))
    image_id: Mapped[str] = mapped_column(String(128))
    __table_args__ = (UniqueConstraint("binding_key", "version"),)


class SSHResourceBinding(Record, Base):
    __tablename__ = "ssh_resource_binding"
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resource_provider.id", ondelete="RESTRICT")
    )
    binding_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int]
    host: Mapped[str] = mapped_column(String(253))
    port: Mapped[int]
    username: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    workdir: Mapped[str] = mapped_column(String(512))
    auth_kind: Mapped[str] = mapped_column(String(16))
    credential_ref: Mapped[str] = mapped_column(String(32))
    native_tool_root: Mapped[str | None] = mapped_column(String(512))
    native_bridge_sha256: Mapped[str | None] = mapped_column(String(64))
    native_lock_sha256: Mapped[str | None] = mapped_column(String(64))
    native_tool_revision: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("binding_key", "version"),
        CheckConstraint(
            "(native_bridge_sha256 IS NULL AND native_lock_sha256 IS NULL AND native_tool_revision IS NULL) OR "
            "(native_tool_root IS NOT NULL AND native_bridge_sha256 IS NOT NULL AND native_lock_sha256 IS NOT NULL AND native_tool_revision IS NOT NULL "
            "AND native_bridge_sha256 ~ '^[0-9a-f]{64}$' AND native_lock_sha256 ~ '^[0-9a-f]{64}$' AND native_tool_revision ~ '^([0-9a-f]{40}|[0-9a-f]{64})$')",
            name="ck_ssh_native_pins",
        ),
    )
