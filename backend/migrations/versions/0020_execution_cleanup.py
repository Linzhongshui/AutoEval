"""Independent durable SSH reclamation state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020_execution_cleanup"
down_revision = "0019_ssh_native_tools"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "execution_cleanup",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.Uuid()),
        sa.Column("claimed_until", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("verified_proofs", JSONB()),
        sa.CheckConstraint("state IN ('pending','running','failed','cleaned')"),
        sa.CheckConstraint("attempt_count >= 0"),
    )
    op.create_index("ix_cleanup_due", "execution_cleanup", ["state", "next_retry_at"])


def downgrade():
    op.drop_table("execution_cleanup")
