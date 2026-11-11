"""Immutable standard source versions and input compilations; no execution enablement."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0023_standard_inputs"
down_revision = "0022_leaderboard_curation"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "standard_input_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("repository", sa.String(256), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("source_model", sa.String(256), nullable=False),
        sa.Column("benchmark", sa.String(128), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("repository", "revision", "source_model", "benchmark"),
        sa.CheckConstraint("revision ~ '^[0-9a-f]{40}$'"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'"),
    )
    op.create_table(
        "standard_input_compilation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "input_id",
            sa.Uuid(),
            sa.ForeignKey("standard_input_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("model_id", sa.Uuid(), sa.ForeignKey("asset.id", ondelete="RESTRICT")),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),
    )
    op.create_index(
        "ix_standard_input_source",
        "standard_input_version",
        ["source_model", "benchmark", "created_at"],
    )
    op.create_index(
        "ix_standard_input_mapping", "standard_input_compilation", ["model_id", "input_id"]
    )
    op.execute("""CREATE FUNCTION standard_input_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Standard input history is immutable'; END $$""")
    for table in ("standard_input_version", "standard_input_compilation"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION standard_input_immutable()"
        )


def downgrade():
    op.drop_table("standard_input_compilation")
    op.drop_table("standard_input_version")
    op.execute("DROP FUNCTION standard_input_immutable()")
