"""Declare immutable customer SSH native tool root."""

import sqlalchemy as sa
from alembic import op

revision = "0019_ssh_native_tools"
down_revision = "0018_ssh_resources"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ssh_resource_binding", sa.Column("native_tool_root", sa.String(512)))


def downgrade():
    op.drop_column("ssh_resource_binding", "native_tool_root")
