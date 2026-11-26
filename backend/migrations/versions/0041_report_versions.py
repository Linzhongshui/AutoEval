"""Preserve report IDs while allowing one current version per task."""

import sqlalchemy as sa
from alembic import op

revision = "0041_report_versions"
down_revision = "0040_execution_rounds"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "evaluation_report", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "evaluation_report",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_unique_constraint(
        "uq_evaluation_report_run_version", "evaluation_report", ["run_id", "version"]
    )
    op.create_index(
        "uq_evaluation_report_current",
        "evaluation_report",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.drop_constraint("evaluation_report_run_id_key", "evaluation_report", type_="unique")


def downgrade():
    # Restoring the former constraint fails safely if multiple versions exist.
    op.create_unique_constraint("evaluation_report_run_id_key", "evaluation_report", ["run_id"])
    op.drop_index("uq_evaluation_report_current", table_name="evaluation_report")
    op.drop_constraint("uq_evaluation_report_run_version", "evaluation_report", type_="unique")
    op.drop_column("evaluation_report", "is_current")
    op.drop_column("evaluation_report", "version")
