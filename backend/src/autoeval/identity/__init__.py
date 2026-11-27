"""Identity domain: OAuth users, one-time authorize states and server-side sessions."""

import logging
from datetime import UTC, datetime

from sqlalchemy import delete

from autoeval.identity.models import OAuthState, UserSession
from autoeval.identity.routes import router

logger = logging.getLogger("autoeval.identity")

__all__ = ["cleanup_expired_identity_rows", "router"]


async def cleanup_expired_identity_rows(sessions) -> None:
    """Delete expired one-time OAuth states and expired server-side sessions.

    被放弃或过期的登录 state、以及到期未登出的会话行会持续累积；
    由 API 生命周期在启动时执行一次并周期调用，保持两表规模受控。
    任何数据库异常只记日志（尽力而为），不拖垮应用启动与运行。
    """
    now = datetime.now(UTC)
    try:
        async with sessions() as session:
            await session.execute(delete(OAuthState).where(OAuthState.expires_at < now))
            await session.execute(delete(UserSession).where(UserSession.expires_at < now))
            await session.commit()
    except Exception:  # 尽力而为：连接失败可能是 OSError/TimeoutError，与配置叠加策略一致
        logger.warning("identity cleanup failed", exc_info=True)
