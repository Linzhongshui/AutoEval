"""Join report review and isolated execution cleanup migrations."""

revision = "0039_merge_report_and_execution"
down_revision = ("0037_report_review", "0038_cleanup_attempt_order")
branch_labels = depends_on = None


def upgrade():
    pass


def downgrade():
    pass
