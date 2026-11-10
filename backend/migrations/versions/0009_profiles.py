"""Versioned profiles and immutable configuration dataset bindings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0009_profiles"
down_revision = "0008_single_full_manifest"
branch_labels = None
depends_on = None


def record_columns():
    return [
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade():
    op.create_table(
        "evaluation_profile",
        *record_columns(),
        sa.Column("profile_key", sa.String(128), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("dataset_name", sa.String(128), nullable=False),
        sa.Column(
            "full_manifest_id",
            pg.UUID(),
            sa.ForeignKey("dataset_manifest.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "lite_manifest_id", pg.UUID(), sa.ForeignKey("dataset_manifest.id", ondelete="RESTRICT")
        ),
        sa.Column("contract", pg.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("profile_key", "version"),
    )
    op.create_table(
        "config_dataset_binding",
        *record_columns(),
        sa.Column(
            "config_item_id",
            pg.UUID(),
            sa.ForeignKey("test_config_item.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "profile_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_profile.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "manifest_id",
            pg.UUID(),
            sa.ForeignKey("dataset_manifest.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_table("config_dataset_binding")
    op.drop_table("evaluation_profile")
