"""Add an explicit approved-history marker to immutable reports."""

import sqlalchemy as sa
from alembic import op

revision = "0037_report_review"
down_revision = "0036_result_revisions"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "evaluation_report",
        sa.Column("review_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column("evaluation_report", sa.Column("reviewed_by", sa.String(256)))
    op.add_column("evaluation_report", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("evaluation_report", sa.Column("review_note", sa.String(1000)))
    op.create_check_constraint(
        "ck_evaluation_report_review_status",
        "evaluation_report",
        "review_status IN ('pending','approved','revoked')",
    )
    op.create_index(
        "ix_report_review_status",
        "evaluation_report",
        ["review_status", "created_at"],
    )


def downgrade():
    op.drop_index("ix_report_review_status", table_name="evaluation_report")
    op.drop_constraint(
        "ck_evaluation_report_review_status", "evaluation_report", type_="check"
    )
    op.drop_column("evaluation_report", "review_note")
    op.drop_column("evaluation_report", "reviewed_at")
    op.drop_column("evaluation_report", "reviewed_by")
    op.drop_column("evaluation_report", "review_status")
