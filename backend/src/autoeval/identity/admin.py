"""Admin-only endpoints: user administration and platform configuration.

Every mutating operation is recorded in ``audit_event`` with the acting
principal, so role changes, suspensions and configuration updates are
traceable through the existing audit query endpoint.
"""

import logging
import uuid as uuid_lib
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.identity.guards import Principal, require_admin
from autoeval.identity.models import PlatformUser, UserSession
from autoeval.infrastructure.audit import record_audit
from autoeval.infrastructure.config import Settings
from autoeval.infrastructure.platform_config import (
    MANAGED_KEYS,
    effective_value,
    save_config_values,
)

logger = logging.getLogger("autoeval.admin")
router = APIRouter(prefix="/api/autoeval/v1/admin", tags=["admin"])

# 路由级统一挂载管理员依赖（共享单例，避免 B008 参数默认值内调用）
ADMIN_GUARD = Depends(require_admin)


def _now() -> datetime:
    return datetime.now(UTC)


def _actor(principal: Principal) -> str:
    return f"{principal.provider}:{principal.login}"


def _user_view(user: PlatformUser) -> dict:
    return {
        "id": str(user.id),
        "provider": user.provider,
        "login": user.login,
        "display_name": user.display_name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "suspended_at": user.suspended_at.isoformat() if user.suspended_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _audit(
    request: Request,
    session,
    principal: Principal,
    *,
    action: str,
    resource_id: str,
    resource_type: str,
    details: dict,
) -> None:
    record_audit(
        session,
        action=action,
        resource_id=resource_id,
        run_id=None,
        outcome="succeeded",
        request_id=request.state.request_id,
        details=details,
        resource_type=resource_type,
        actor=_actor(principal),
    )


async def _ensure_not_last_superadmin(session, user_id, action: str) -> None:
    """处置超级管理员前校验：必须存在另一位未停用的超级管理员。"""
    others = (
        await session.execute(
            select(func.count())
            .select_from(PlatformUser)
            .where(
                PlatformUser.role == "superadmin",
                PlatformUser.suspended_at.is_(None),
                PlatformUser.id != user_id,
            )
        )
    ).scalar_one()
    if others == 0:
        raise HTTPException(409, f"最后一个有效超级管理员不可{action}")


@router.get("/users")
async def list_users(
    request: Request,
    principal: Principal = ADMIN_GUARD,
    offset: int = 0,
    limit: int = 50,
    q: str | None = None,
):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    try:
        async with request.app.state.sessions() as session:
            query = select(PlatformUser)
            if q:
                pattern = f"%{q.strip()}%"
                query = query.where(
                    or_(
                        PlatformUser.login.ilike(pattern),
                        PlatformUser.display_name.ilike(pattern),
                        PlatformUser.email.ilike(pattern),
                    )
                )
            total = (
                await session.execute(select(func.count()).select_from(query.subquery()))
            ).scalar_one()
            rows = (
                await session.scalars(
                    query.order_by(PlatformUser.created_at.desc(), PlatformUser.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
            data = [_user_view(row) for row in rows[:limit]]
    except SQLAlchemyError as exc:
        logger.exception("list users failed")
        raise HTTPException(503, "用户数据库不可用") from exc
    return {
        "data": data,
        "total": total,
        "next_offset": offset + limit if len(rows) > limit else None,
        "request_id": request.state.request_id,
    }


class UserPatch(BaseModel):
    role: Literal["superadmin", "admin", "regular"] | None = None
    suspended: bool | None = None


@router.patch("/users/{user_id}")
async def update_user(
    request: Request,
    user_id: uuid_lib.UUID,
    patch: UserPatch,
    principal: Principal = ADMIN_GUARD,
):
    if patch.role is None and patch.suspended is None:
        raise HTTPException(422, "没有需要更新的字段")
    try:
        async with request.app.state.sessions() as session:
            target = await session.get(PlatformUser, user_id)
            if target is None:
                raise HTTPException(404, "用户不存在")
            changes: dict[str, Any] = {}
            if patch.role is not None and patch.role != target.role:
                # 角色调整（任何方向，含设超管）仅超级管理员可执行；
                # 管理员不能提拔普通用户，也不能降级其他管理员。
                if principal.role != "superadmin":
                    raise HTTPException(403, "仅超级管理员可以调整角色")
                if target.role == "superadmin" and patch.role != "superadmin":
                    await _ensure_not_last_superadmin(session, target.id, action="降级")
                changes["role"] = {"from": target.role, "to": patch.role}
                target.role = patch.role
            if patch.suspended is not None and (target.suspended_at is not None) != patch.suspended:
                if target.role != "regular" and principal.role != "superadmin":
                    # 管理员只能停用/恢复普通用户，不能互相停用，不能动超管
                    raise HTTPException(403, "仅超级管理员可以停用管理员或超级管理员")
                if patch.suspended and target.role == "superadmin":
                    await _ensure_not_last_superadmin(session, target.id, action="停用")
                if patch.suspended:
                    # 停用即吊销该用户全部会话，已登录会话立刻失效
                    revoked = (
                        await session.execute(
                            delete(UserSession)
                            .where(UserSession.user_id == target.id)
                            .returning(UserSession.id)
                        )
                    ).all()
                    target.suspended_at = _now()
                    changes["suspended"] = {"to": True, "revoked_sessions": len(revoked)}
                else:
                    target.suspended_at = None
                    changes["suspended"] = {"to": False}
            if not changes:
                return {"data": _user_view(target), "request_id": request.state.request_id}
            _audit(
                request,
                session,
                principal,
                action="user.update",
                resource_id=str(target.id),
                resource_type="platform_user",
                details={"changes": changes},
            )
            await session.commit()
    except SQLAlchemyError as exc:
        logger.exception("update user failed user_id=%s", user_id)
        raise HTTPException(503, "用户更新失败，请重试") from exc
    return {"data": _user_view(target), "request_id": request.state.request_id}


@router.get("/config")
async def get_config(request: Request, principal: Principal = ADMIN_GUARD):
    settings: Settings = request.app.state.settings
    data = {key: effective_value(settings, key) for key in MANAGED_KEYS}
    data["billing_execution_config"] = (
        str(settings.billing_execution_config) if settings.billing_execution_config else None
    )
    return {"data": data, "request_id": request.state.request_id}


class ConfigUpdate(BaseModel):
    updates: dict[str, Any]


@router.put("/config")
async def update_config(
    request: Request,
    body: ConfigUpdate,
    principal: Principal = ADMIN_GUARD,
):
    settings: Settings = request.app.state.settings
    if not body.updates:
        raise HTTPException(422, "没有需要更新的配置")
    actor = _actor(principal)
    try:
        applied = await save_config_values(
            request.app.state.sessions, settings, body.updates, actor
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.exception("save platform_config failed")
        raise HTTPException(503, "配置保存失败，请重试") from exc
    try:
        async with request.app.state.sessions() as session:
            _audit(
                request,
                session,
                principal,
                action="config.update",
                resource_id="platform-config",
                resource_type="platform_config",
                details={"updates": applied},
            )
            await session.commit()
    except SQLAlchemyError:
        # 配置已保存并生效；审计落库失败不影响管理操作结果，但必须记录日志
        logger.exception("audit config.update failed")
    return {
        "data": {key: effective_value(settings, key) for key in MANAGED_KEYS},
        "request_id": request.state.request_id,
    }
