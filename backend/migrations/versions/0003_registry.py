"""Model assets, versions and default configuration binding."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003_registry"
down_revision = "0002_configuration"
branch_labels = None
depends_on = None


def base():
    return [
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "asset",
        *base(),
        sa.Column("asset_key", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
    )
    op.create_table(
        "asset_version",
        *base(),
        sa.Column(
            "asset_id", pg.UUID(), sa.ForeignKey("asset.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("metadata", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("asset_id", "version"),
    )
    op.create_table(
        "model_config_binding",
        *base(),
        sa.Column(
            "model_asset_id",
            pg.UUID(),
            sa.ForeignKey("asset.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "default_config_version_id",
            pg.UUID(),
            sa.ForeignKey("test_config_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade():
    op.drop_table("model_config_binding")
    op.drop_table("asset_version")
    op.drop_table("asset")
