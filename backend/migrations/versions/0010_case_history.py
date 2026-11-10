"""Indexed case attempts and object-backed immutable evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0010_case_history"
down_revision = "0009_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_execution_record",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "run_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dataset_key", sa.String(128), nullable=False),
        sa.Column("sample_id", sa.String(256), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.String(256), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("object_key", sa.String(256)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.UniqueConstraint("run_id", "operation_key"),
        sa.UniqueConstraint("run_id", "dataset_key", "sample_id", "attempt_no"),
        sa.CheckConstraint("attempt_no > 0"),
        sa.CheckConstraint("state IN ('started','succeeded','failed')"),
        sa.CheckConstraint(
            "(state = 'started' AND finished_at IS NULL AND object_key IS NULL AND sha256 IS NULL) OR (state <> 'started' AND finished_at IS NOT NULL AND object_key IS NOT NULL AND sha256 IS NOT NULL)"
        ),
    )
    op.create_index(
        "ix_case_history_run_sample",
        "case_execution_record",
        ["run_id", "dataset_key", "sample_id", "attempt_no"],
    )


def downgrade():
    op.drop_table("case_execution_record")
