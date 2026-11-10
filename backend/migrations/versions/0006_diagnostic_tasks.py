"""Exclusive container lease and diagnostic-only result summary."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0006_diagnostic_tasks"
down_revision = "0005_resources"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "execution_lease",
        sa.Column("container_id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
    )
    op.create_table(
        "diagnostic_result",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "run_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("summary", pg.JSONB(), nullable=False),
    )


def downgrade():
    op.drop_table("diagnostic_result")
    op.drop_table("execution_lease")
