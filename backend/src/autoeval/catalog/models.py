"""Catalog ORM models: assets, versions, manifests, profiles, configurations and baselines."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.infrastructure.models import Base, Record


class Asset(Record, Base):
    __tablename__ = "asset"
    asset_key: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(256))


class AssetVersion(Record, Base):
    __tablename__ = "asset_version"
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asset.id", ondelete="RESTRICT"))
    version: Mapped[str] = mapped_column(String(128))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB)
    __table_args__ = (UniqueConstraint("asset_id", "version"),)


class ModelConfigBinding(Record, Base):
    __tablename__ = "model_config_binding"
    model_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset.id", ondelete="RESTRICT"), unique=True
    )
    default_config_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_config_version.id", ondelete="RESTRICT")
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default="1")


class DatasetManifest(Record, Base):
    __tablename__ = "dataset_manifest"
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset_version.id", ondelete="RESTRICT")
    )
    manifest_key: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(8))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_manifest.id", ondelete="RESTRICT")
    )
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(256))
    sample_count: Mapped[int]
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "manifest_key"),
        Index(
            "uq_dataset_full_manifest",
            "dataset_version_id",
            unique=True,
            postgresql_where=text("scope = 'full'"),
        ),
        CheckConstraint("sample_count > 0"),
        CheckConstraint(
            "(scope = 'full' AND parent_id IS NULL) OR (scope = 'lite' AND parent_id IS NOT NULL)"
        ),
    )


class EvaluationProfile(Record, Base):
    __tablename__ = "evaluation_profile"
    profile_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(128))
    dataset_name: Mapped[str] = mapped_column(String(128))
    full_manifest_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_manifest.id", ondelete="RESTRICT")
    )
    lite_manifest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_manifest.id", ondelete="RESTRICT")
    )
    contract: Mapped[dict] = mapped_column(JSONB)
    sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("profile_key", "version"),)


class ConfigDatasetBinding(Record, Base):
    __tablename__ = "config_dataset_binding"
    config_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_config_item.id", ondelete="RESTRICT"), unique=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_profile.id", ondelete="RESTRICT")
    )
    manifest_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_manifest.id", ondelete="RESTRICT")
    )


class TestConfigVersion(Record, Base):
    __tablename__ = "test_config_version"
    config_key: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(256))
    version: Mapped[int] = mapped_column(Integer)
    version_label: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(256))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_revision: Mapped[str | None] = mapped_column(String(256))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[str | None] = mapped_column(String(256))
    __table_args__ = (
        UniqueConstraint("config_key", "version"),
        UniqueConstraint("config_key", "version_label"),
        CheckConstraint("version > 0"),
        CheckConstraint("kind IN ('standard','custom')"),
        CheckConstraint(
            "(kind = 'standard' AND source_url IS NOT NULL AND source_revision IS NOT NULL "
            "AND source_sha256 IS NOT NULL) OR "
            "(kind = 'custom' AND source_url IS NULL AND source_revision IS NULL "
            "AND source_sha256 IS NULL AND approved_by IS NULL)",
            name="ck_standard_config_metadata",
        ),
        CheckConstraint(
            "(source_url IS NULL OR source_url LIKE 'https://%') AND "
            "(source_revision IS NULL OR length(source_revision) > 0) AND "
            "(source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$') AND "
            "(approved_by IS NULL OR length(approved_by) > 0)",
            name="ck_standard_config_source_values",
        ),
    )


class TestConfigItem(Record, Base):
    __tablename__ = "test_config_item"
    config_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_config_version.id", ondelete="RESTRICT")
    )
    dataset_key: Mapped[str] = mapped_column(String(128))
    parameter_values: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("config_version_id", "dataset_key"),)


class BenchmarkBaseline(Record, Base):
    __tablename__ = "benchmark_baseline"
    baseline_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(128))
    dataset_key: Mapped[str] = mapped_column(String(128))
    subset_scope: Mapped[str] = mapped_column(String(8))
    metric_name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(32))
    value: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(16))
    conditions: Mapped[dict] = mapped_column(JSONB)
    source_url: Mapped[str] = mapped_column(String(1024))
    source_revision: Mapped[str] = mapped_column(String(256))
    source_sha256: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str] = mapped_column(String(256))
    content_sha256: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint(
            "baseline_key",
            "version",
            "dataset_key",
            "subset_scope",
            "metric_name",
            name="uq_benchmark_baseline_identity",
        ),
        CheckConstraint(
            "direction IN ('higher_is_better','lower_is_better')",
            name="ck_benchmark_baseline_direction",
        ),
        CheckConstraint(
            "value > '-Infinity' AND value < 'Infinity'",
            name="ck_benchmark_baseline_finite_value",
        ),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_benchmark_baseline_source_sha256",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_benchmark_baseline_content_sha256",
        ),
        CheckConstraint("source_url LIKE 'https://%'", name="ck_benchmark_baseline_source_https"),
        CheckConstraint(
            "subset_scope IN ('full','lite')", name="ck_benchmark_baseline_subset_scope"
        ),
    )
