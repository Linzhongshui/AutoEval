"""Independent customer SSH resource bindings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0018_ssh_resources"
down_revision = "0017_audit_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ssh_resource_binding",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "provider_id",
            pg.UUID(),
            sa.ForeignKey("resource_provider.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("binding_key", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("workdir", sa.String(512), nullable=False),
        sa.Column("auth_kind", sa.String(16), nullable=False),
        sa.Column("credential_ref", sa.String(32), nullable=False),
        sa.UniqueConstraint("binding_key", "version"),
    )


def downgrade():
    op.drop_table("ssh_resource_binding")
