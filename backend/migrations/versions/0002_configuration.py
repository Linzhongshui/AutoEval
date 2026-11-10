"""Custom test configuration revisions and per-dataset parameters."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002_configuration"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "test_config_version",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("config_key", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.UniqueConstraint("config_key", "version"),
        sa.UniqueConstraint("config_key", "version_label"),
        sa.CheckConstraint("version > 0"),
        sa.CheckConstraint("kind IN ('standard','custom')"),
    )
    op.create_table(
        "test_config_item",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "config_version_id",
            pg.UUID(),
            sa.ForeignKey("test_config_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dataset_key", sa.String(128), nullable=False),
        sa.Column("parameter_values", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("config_version_id", "dataset_key"),
    )


def downgrade():
    op.drop_table("test_config_item")
    op.drop_table("test_config_version")
