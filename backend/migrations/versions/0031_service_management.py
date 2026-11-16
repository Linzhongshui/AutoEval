"""Service display names and non-destructive removal."""

import sqlalchemy as sa
from alembic import op

revision = "0031_service_management"
down_revision = "0030_analysis_reanalysis"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "target_binding_version",
        sa.Column("service_name", sa.String(128), nullable=False, server_default=""),
    )
    op.add_column(
        "target_binding_version",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("target_binding_version", "archived")
    op.drop_column("target_binding_version", "service_name")
