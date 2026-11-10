"""Initial single-workspace execution foundation (no business submission API yet)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def base():
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "evaluation_run",
        *base(),
        sa.Column("trigger_scope", sa.String(256), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="accepted"),
        sa.Column("run_mode", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("projection_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.UniqueConstraint("trigger_scope", "idempotency_key"),
        sa.CheckConstraint("run_mode IN ('exploration','release_validation')"),
        sa.CheckConstraint(
            "state IN ('accepted','queued','preparing','running','aggregating','completed','cancelling','cancelled','failed')"
        ),
    )
    op.create_index("ix_run_created", "evaluation_run", ["created_at", "id"])
    op.create_table(
        "run_snapshot",
        *base(),
        sa.Column(
            "run_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("canonical_body", pg.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
    )
    op.create_table(
        "run_event",
        *base(),
        sa.Column(
            "run_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("body", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "seq"),
        sa.CheckConstraint("seq > 0"),
    )
    op.create_table(
        "outbox",
        *base(),
        sa.Column(
            "run_id",
            pg.UUID(),
            sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("dedup_key", sa.String(256), nullable=False, unique=True),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("kind IN ('START_RUN','CANCEL_RUN')"),
        sa.CheckConstraint("state IN ('pending','delivered')"),
        sa.CheckConstraint("attempt_count >= 0"),
    )
    op.create_index(
        "ix_outbox_pending",
        "outbox",
        ["next_retry_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )


def downgrade():
    for name in ["outbox", "run_event", "run_snapshot", "evaluation_run"]:
        op.drop_table(name)
