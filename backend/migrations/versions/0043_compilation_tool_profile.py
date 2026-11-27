"""Allow tool profiles scoped to a frozen execution compilation."""

import sqlalchemy as sa
from alembic import op

revision = "0043_compilation_tool_profile"
down_revision = "0042_target_service_kind"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "evaluation_profile",
        sa.Column("compilation_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_evaluation_profile_compilation",
        "evaluation_profile",
        "standard_input_compilation",
        ["compilation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_evaluation_profile_compilation_id", "evaluation_profile", ["compilation_id"])


def downgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM evaluation_profile WHERE compilation_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Compilation-scoped profiles must be removed before downgrade';
            END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_evaluation_profile_compilation_id", table_name="evaluation_profile")
    op.drop_constraint(
        "fk_evaluation_profile_compilation", "evaluation_profile", type_="foreignkey"
    )
    op.drop_column("evaluation_profile", "compilation_id")
