"""Durable per-attempt Langfuse import records."""

import sqlalchemy as sa
from alembic import op

revision = "0032_langfuse"
down_revision = "0031_service_management"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "langfuse_trace_import",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("run_id", sa.UUID(), sa.ForeignKey("evaluation_run.id"), nullable=False),
        sa.Column(
            "attempt_id", sa.UUID(), sa.ForeignKey("case_execution_record.id"), nullable=False
        ),
        sa.Column("langfuse_project", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(256), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.String(32)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("retry_no", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("attempt_id", "langfuse_project"),
    )


def downgrade():
    op.drop_table("langfuse_trace_import")
