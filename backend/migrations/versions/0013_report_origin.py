"""Keep simulated and unverified historical reports out of the real catalog."""

import sqlalchemy as sa
from alembic import op

revision = "0013_report_origin"
down_revision = "0012_evaluation_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "evaluation_report",
        sa.Column("execution_origin", sa.String(16), nullable=False, server_default="unverified"),
    )
    op.create_check_constraint(
        "ck_report_origin",
        "evaluation_report",
        "execution_origin IN ('real','simulation','unverified')",
    )


def downgrade():
    op.drop_constraint("ck_report_origin", "evaluation_report", type_="check")
    op.drop_column("evaluation_report", "execution_origin")
