"""Rotate failed execution environment cleanup attempts."""

import sqlalchemy as sa
from alembic import op

revision = "0038_cleanup_attempt_order"
down_revision = "0037_execution_environment"


def upgrade():
    op.add_column(
        "dataset_execution_environment",
        sa.Column("cleanup_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("dataset_execution_environment", "cleanup_attempted_at")
