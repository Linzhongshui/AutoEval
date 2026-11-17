"""Freeze trace content mode; preserve historical structural exports."""

import sqlalchemy as sa
from alembic import op

revision = "0033_langfuse_content_mode"
down_revision = "0032_langfuse"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "langfuse_trace_import",
        sa.Column("content_mode", sa.String(16), nullable=False, server_default="structural"),
    )


def downgrade():
    op.drop_column("langfuse_trace_import", "content_mode")
