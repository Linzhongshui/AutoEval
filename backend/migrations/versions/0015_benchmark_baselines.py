"""Approved, immutable JSON benchmark baselines with full provenance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0015_benchmark_baselines"
down_revision = "0014_standard_config"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "benchmark_baseline",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("baseline_key", sa.String(128), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("dataset_key", sa.String(128), nullable=False),
        sa.Column("subset_scope", sa.String(8), nullable=False),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("conditions", pg.JSONB(), nullable=False),
        sa.Column("source_url", sa.String(1024), nullable=False),
        sa.Column("source_revision", sa.String(256), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("approved_by", sa.String(256), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "baseline_key",
            "version",
            "dataset_key",
            "subset_scope",
            "metric_name",
            name="uq_benchmark_baseline_identity",
        ),
        sa.CheckConstraint(
            "direction IN ('higher_is_better','lower_is_better')",
            name="ck_benchmark_baseline_direction",
        ),
        sa.CheckConstraint(
            "value > '-Infinity' AND value < 'Infinity'",
            name="ck_benchmark_baseline_finite_value",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_benchmark_baseline_source_sha256",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_benchmark_baseline_content_sha256",
        ),
        sa.CheckConstraint(
            "source_url LIKE 'https://%'", name="ck_benchmark_baseline_source_https"
        ),
        sa.CheckConstraint(
            "subset_scope IN ('full','lite')", name="ck_benchmark_baseline_subset_scope"
        ),
    )
    op.execute("""
    CREATE FUNCTION protect_benchmark_baseline() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'Benchmark baselines are immutable';
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    CREATE TRIGGER benchmark_baseline_immutable BEFORE UPDATE OR DELETE ON benchmark_baseline
      FOR EACH ROW EXECUTE FUNCTION protect_benchmark_baseline();
    """)


def downgrade():
    op.execute("DROP TRIGGER benchmark_baseline_immutable ON benchmark_baseline")
    op.execute("DROP FUNCTION protect_benchmark_baseline()")
    op.drop_table("benchmark_baseline")
