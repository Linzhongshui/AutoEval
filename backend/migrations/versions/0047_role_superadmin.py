"""Superadmin role: widen the role constraint and promote the first superadmin.

Existing gitcode-platform admins become superadmins (this deployment's owner
account); github admins stay admins. Role changes themselves are henceforth
restricted to superadmins at the API layer.
"""

from alembic import op

revision = "0047_role_superadmin"
down_revision = "0046_platform_config"
branch_labels = depends_on = None

ROLE_CHECK = "ck_platform_user_role"


def upgrade():
    op.execute(f"ALTER TABLE platform_user DROP CONSTRAINT {ROLE_CHECK}")
    op.execute(
        f"ALTER TABLE platform_user ADD CONSTRAINT {ROLE_CHECK} "
        "CHECK (role IN ('superadmin','admin','regular'))"
    )
    # 首位超管：部署所有者账号（gitcode）一次性升为超管；github 管理员保持不变
    op.execute(
        "UPDATE platform_user SET role = 'superadmin' WHERE provider = 'gitcode' AND role = 'admin'"
    )


def downgrade():
    op.execute(
        "UPDATE platform_user SET role = 'admin' WHERE provider = 'gitcode' AND role = 'superadmin'"
    )
    op.execute(f"ALTER TABLE platform_user DROP CONSTRAINT {ROLE_CHECK}")
    op.execute(
        f"ALTER TABLE platform_user ADD CONSTRAINT {ROLE_CHECK} CHECK (role IN ('admin','regular'))"
    )
