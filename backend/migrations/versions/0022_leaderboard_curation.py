"""Reviewed leaderboard records, separate from immutable report evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0022_leaderboard_curation"
down_revision = "0021_ssh_artifact_pins"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "leaderboard_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False, unique=True),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("evaluation_report.id")),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.CheckConstraint("state IN ('draft','approved','rejected','withdrawn')"),
        sa.CheckConstraint("revision > 0"),
    )
    op.create_index("ix_leaderboard_record_state", "leaderboard_record", ["state", "created_at", "id"])


def downgrade():
    op.drop_table("leaderboard_record")
