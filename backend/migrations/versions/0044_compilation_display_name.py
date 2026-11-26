"""Keep editable names outside immutable execution snapshots."""
import sqlalchemy as sa
from alembic import op

revision = "0044_compilation_display_name"
down_revision = "0043_compilation_tool_profile"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("compilation_display_name",
        sa.Column("compilation_id", sa.Uuid(), sa.ForeignKey("standard_input_compilation.id"), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False))


def downgrade():
    op.drop_table("compilation_display_name")
