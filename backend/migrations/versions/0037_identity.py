"""OAuth identity: platform users, one-time authorize states and server-side sessions."""

from alembic import op

from autoeval.identity.models import OAuthState, PlatformUser, UserSession

revision = "0037_identity"
down_revision = "0036_result_revisions"
branch_labels = depends_on = None


def upgrade():
    PlatformUser.__table__.create(op.get_bind())
    OAuthState.__table__.create(op.get_bind())
    UserSession.__table__.create(op.get_bind())


def downgrade():
    UserSession.__table__.drop(op.get_bind())
    OAuthState.__table__.drop(op.get_bind())
    PlatformUser.__table__.drop(op.get_bind())
