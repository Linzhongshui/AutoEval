"""Append-only local-operator audit events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0017_audit_events"
down_revision = "0016_report_analysis"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_event",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor", sa.String(256), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("evaluation_run.id", ondelete="RESTRICT")),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("details", pg.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_audit_event_resource", "audit_event",
        ["resource_type", "resource_id", "created_at", "id"],
    )
    op.create_index("ix_audit_event_run", "audit_event", ["run_id", "created_at", "id"])
    op.execute("""
    CREATE FUNCTION protect_audit_event() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'Audit events are immutable';
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    CREATE TRIGGER audit_event_immutable BEFORE UPDATE OR DELETE ON audit_event
      FOR EACH ROW EXECUTE FUNCTION protect_audit_event();
    """)


def downgrade():
    op.execute("DROP TRIGGER audit_event_immutable ON audit_event")
    op.execute("DROP FUNCTION protect_audit_event()")
    op.drop_index("ix_audit_event_run", table_name="audit_event")
    op.drop_index("ix_audit_event_resource", table_name="audit_event")
    op.drop_table("audit_event")
