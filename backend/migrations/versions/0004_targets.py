"""API targets and separate connection observations; credentials remain external."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004_targets"
down_revision = "0003_registry"
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
        "target_binding_version",
        *base(),
        sa.Column(
            "model_version_id",
            pg.UUID(),
            sa.ForeignKey("asset_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("remote_model", sa.String(128), nullable=False),
        sa.Column("credential_ref", sa.String(32), nullable=False),
    )
    op.create_table(
        "connection_probe",
        *base(),
        sa.Column(
            "target_id",
            pg.UUID(),
            sa.ForeignKey("target_binding_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("details", pg.JSONB(), nullable=False),
    )


def downgrade():
    op.drop_table("connection_probe")
    op.drop_table("target_binding_version")
