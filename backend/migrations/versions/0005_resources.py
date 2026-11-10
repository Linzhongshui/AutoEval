"""Local Docker provider and immutable executor binding identity."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005_resources"
down_revision = "0004_targets"
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
        "resource_provider",
        *base(),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=False),
    )
    op.create_table(
        "resource_binding_version",
        *base(),
        sa.Column(
            "provider_id",
            pg.UUID(),
            sa.ForeignKey("resource_provider.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("binding_key", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("container_id", sa.String(64), nullable=False),
        sa.Column("image_id", sa.String(128), nullable=False),
        sa.UniqueConstraint("binding_key", "version"),
    )


def downgrade():
    op.drop_table("resource_binding_version")
    op.drop_table("resource_provider")
