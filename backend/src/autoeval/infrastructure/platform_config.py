"""Admin-managed platform configuration persisted in PostgreSQL.

Stored values are overlaid onto the runtime ``Settings`` instance (the same
object shared by ``app.state.settings`` and ``get_settings()``) at startup and
after every update, so request-time consumers — the budget middleware and
Langfuse link builders — pick up changes without a restart.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.infrastructure.config import Settings
from autoeval.infrastructure.models import Base, Record

logger = logging.getLogger("autoeval.platform_config")


class PlatformConfig(Record, Base):
    """One row per managed key; ``value`` wraps the payload as ``{"value": ...}``."""

    __tablename__ = "platform_config"
    key: Mapped[str] = mapped_column(String(64), unique=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_by: Mapped[str] = mapped_column(String(256))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def _as_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError("必须是布尔值")
    return value


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("必须是字符串或 null")
    return value


# Whitelist of keys admins may change; converter validates and normalizes raw payloads.
MANAGED_KEYS: dict[str, Callable[[Any], Any]] = {
    "enforce_task_budget": _as_bool,
    "evaluation_follow_up_enabled": _as_bool,
    "langfuse_browser_url": _as_str_or_none,
    "langfuse_host": _as_str_or_none,
    "langfuse_project_id": _as_str_or_none,
}


def apply_value(settings: Settings, key: str, value: Any) -> Any:
    """Convert, assign onto the runtime settings and return the stored value."""
    converter = MANAGED_KEYS.get(key)
    if converter is None:
        return None  # unknown keys are ignored (forward compatibility)
    converted = converter(value)
    setattr(settings, key, converted)
    return converted


def effective_value(settings: Settings, key: str) -> Any:
    """Current effective value for a managed key."""
    return getattr(settings, key)


async def load_config_overlay(sessions, settings: Settings) -> None:
    """Restore stored values onto settings at startup; failures keep defaults.

    数据库不可达或驱动抛任意异常（asyncpg 连接失败为 OSError/TimeoutError，
    不一定是 SQLAlchemyError）都不允许拖垮应用启动。
    """
    try:
        async with sessions() as session:
            rows = (await session.scalars(select(PlatformConfig))).all()
    except Exception:  # 启动覆盖尽力而为：任何失败都回退默认值，不拖垮应用启动
        logger.warning("load platform_config failed; runtime defaults kept", exc_info=True)
        return
    for row in rows:
        payload = row.value.get("value") if isinstance(row.value, dict) else None
        try:
            apply_value(settings, row.key, payload)
        except (TypeError, ValueError):
            logger.warning("ignore invalid stored config key=%s", row.key, exc_info=True)


async def save_config_values(sessions, settings: Settings, updates: dict, actor: str) -> dict:
    """Validate, persist and apply updates; returns the JSON-safe applied values.

    校验与转换在写库前完成，提交成功后才把新值应用到运行中的 ``Settings``：
    任一键校验失败（422）或提交失败（503）时，内存与存储都不会部分生效。
    """
    converted: dict[str, Any] = {}
    for key, raw in updates.items():
        if key not in MANAGED_KEYS:
            raise ValueError(f"未知配置项: {key}")
        converted[key] = MANAGED_KEYS[key](raw)  # raises TypeError/ValueError before any write
    applied: dict[str, Any] = {}
    async with sessions() as session:
        for key, value in converted.items():
            stored = (
                await session.execute(select(PlatformConfig).where(PlatformConfig.key == key))
            ).scalar_one_or_none()
            if stored is None:
                session.add(PlatformConfig(key=key, value={"value": value}, updated_by=actor))
            else:
                stored.value = {"value": value}
                stored.updated_by = actor
            applied[key] = value
        await session.commit()
    for key, value in converted.items():
        setattr(settings, key, value)
    return applied
