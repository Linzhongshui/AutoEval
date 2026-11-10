"""Immutable object-backed dataset manifests."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007_dataset_manifests"
down_revision = "0006_diagnostic_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dataset_manifest",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "dataset_version_id",
            pg.UUID(),
            sa.ForeignKey("asset_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("manifest_key", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.Column(
            "parent_id", pg.UUID(), sa.ForeignKey("dataset_manifest.id", ondelete="RESTRICT")
        ),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(256), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("dataset_version_id", "manifest_key"),
        sa.CheckConstraint("sample_count > 0"),
        sa.CheckConstraint(
            "(scope = 'full' AND parent_id IS NULL) OR (scope = 'lite' AND parent_id IS NOT NULL)"
        ),
    )


def downgrade():
    op.drop_table("dataset_manifest")
