"""Track the dedicated container allocated to an evaluation subtask."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0037_execution_environment"
down_revision = "0036_result_revisions"


def upgrade():
    op.create_table(
        "dataset_execution_environment",
        sa.Column("dataset_execution_id", sa.Uuid(), sa.ForeignKey("dataset_execution.id"), primary_key=True),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("ssh_resource_binding.id"), nullable=False),
        sa.Column("template", JSONB(), nullable=False),
        sa.Column("container_id", sa.String(64)),
        sa.Column("state", sa.String(24), nullable=False),
    )
    op.create_index("ix_dataset_execution_environment_state", "dataset_execution_environment", ["state"])


def downgrade():
    op.drop_table("dataset_execution_environment")
