"""Approved source and approval metadata for standard configurations."""

import sqlalchemy as sa
from alembic import op

revision = "0014_standard_config"
down_revision = "0013_report_origin"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("test_config_version", sa.Column("source_url", sa.String(2048), nullable=True))
    op.add_column(
        "test_config_version", sa.Column("source_revision", sa.String(256), nullable=True)
    )
    op.add_column("test_config_version", sa.Column("source_sha256", sa.String(64), nullable=True))
    op.add_column("test_config_version", sa.Column("approved_by", sa.String(256), nullable=True))
    op.create_check_constraint(
        "ck_standard_config_metadata",
        "test_config_version",
        "(kind = 'standard' AND source_url IS NOT NULL AND source_revision IS NOT NULL "
        "AND source_sha256 IS NOT NULL AND approved_by IS NOT NULL) OR "
        "(kind = 'custom' AND source_url IS NULL AND source_revision IS NULL "
        "AND source_sha256 IS NULL AND approved_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_standard_config_source_values",
        "test_config_version",
        "(source_url IS NULL OR source_url LIKE 'https://%') AND "
        "(source_revision IS NULL OR length(source_revision) > 0) AND "
        "(source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$') AND "
        "(approved_by IS NULL OR length(approved_by) > 0)",
    )


def downgrade():
    op.drop_constraint("ck_standard_config_source_values", "test_config_version", type_="check")
    op.drop_constraint("ck_standard_config_metadata", "test_config_version", type_="check")
    op.drop_column("test_config_version", "approved_by")
    op.drop_column("test_config_version", "source_sha256")
    op.drop_column("test_config_version", "source_revision")
    op.drop_column("test_config_version", "source_url")
