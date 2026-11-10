"""Independent one-shot report analysis and evidence citation catalog."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0016_report_analysis"
down_revision = "0015_benchmark_baselines"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_analysis",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "report_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_report.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "run_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("trigger", sa.String(24), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("baseline_comparison_sha256", sa.String(64)),
        sa.Column("baseline_comparison", pg.JSONB()),
        sa.Column("target_snapshot", pg.JSONB(), nullable=False),
        sa.Column("evidence_catalog", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("input_object_key", sa.String(256)),
        sa.Column("input_sha256", sa.String(64)),
        sa.Column("object_key", sa.String(256)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("usage", pg.JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('queued','running','succeeded','failed','unresolved')",
            name="ck_report_analysis_state",
        ),
        sa.CheckConstraint(
            "trigger IN ('report_created','manual_retry')", name="ck_report_analysis_trigger"
        ),
        sa.CheckConstraint("retry_count BETWEEN 0 AND 1", name="ck_report_analysis_retry_count"),
        sa.CheckConstraint(
            "report_sha256 ~ '^[0-9a-f]{64}$'", name="ck_report_analysis_report_sha"
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_report_analysis_snapshot_sha"
        ),
    )
    op.create_index("ix_report_analysis_run", "report_analysis", ["run_id"])
    op.create_index("ix_report_analysis_state", "report_analysis", ["state", "created_at"])
    op.drop_constraint("outbox_kind_check", "outbox", type_="check")
    op.create_check_constraint(
        "ck_outbox_kind", "outbox", "kind IN ('START_RUN','CANCEL_RUN','ANALYZE_REPORT')"
    )


def downgrade():
    op.drop_constraint("ck_outbox_kind", "outbox", type_="check")
    op.create_check_constraint(
        "outbox_kind_check", "outbox", "kind IN ('START_RUN','CANCEL_RUN')"
    )
    op.drop_index("ix_report_analysis_state", table_name="report_analysis")
    op.drop_index("ix_report_analysis_run", table_name="report_analysis")
    op.drop_table("report_analysis")
