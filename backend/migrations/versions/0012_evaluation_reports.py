"""Immutable run report metadata; report details live in object storage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0012_evaluation_reports"
down_revision = "0011_immutable_case_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_report",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "run_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("validity", sa.String(24), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("summary", pg.JSONB(), nullable=False),
        sa.Column("object_key", sa.String(256), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
    )


def downgrade():
    op.drop_table("evaluation_report")
