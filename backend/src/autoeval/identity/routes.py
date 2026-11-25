"""OAuth login / logout / current-user endpoints for GitHub and GitCode."""

import logging
import secrets
import uuid as uuid_lib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.identity.guards import SESSION_COOKIE, local_principal, resolve_principal
from autoeval.identity.models import OAuthState, PlatformUser, UserSession
from autoeval.identity.providers import OAuthFlowError, available_providers
from autoeval.infrastructure.config import Settings

logger = logging.getLogger("autoeval.identity")
router = APIRouter(prefix="/api/autoeval/v1/auth", tags=["auth"])

STATE_COOKIE = "ae_oauth_state"
STATE_COOKIE_PATH = "/api/autoeval/v1/auth/callback"
STATE_TTL_MINUTES = 5


def _now() -> datetime:
    return datetime.now(UTC)


def _cookie_params(settings: Settings) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.environment == "production",
    }


def _login_error(settings: Settings, code: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.frontend_origin.rstrip('/')}/#login?error={code}", status_code=302
    )


def _state_cookie_error(settings: Settings, code: str) -> RedirectResponse:
    """登录流程已终结的错误跳转，同时清除一次性 state Cookie。"""
    response = _login_error(settings, code)
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH, **_cookie_params(settings))
    return response


def _admin_accounts(settings: Settings) -> set[str]:
    """AE_ADMIN_ACCOUNTS：逗号分隔的 ``provider:provider_uid`` 条目。

    使用平台下发的稳定 provider_uid 而非可变登录名，登录名修改不影响首管理员引导。
    """
    return {entry.strip() for entry in settings.admin_accounts if ":" in entry}


def _superadmin_accounts(settings: Settings) -> set[str]:
    """AE_SUPERADMIN_ACCOUNTS：同上格式，用于首超级管理员引导。"""
    return {entry.strip() for entry in settings.superadmin_accounts if ":" in entry}


@router.get("/providers")
async def providers(request: Request):
    settings: Settings = request.app.state.settings
    return {
        "data": [
            {"provider": flow.key, "display_name": flow.display_name}
            for flow in available_providers(settings).values()
        ]
    }


@router.get("/login/{provider}")
async def login(request: Request, provider: str):
    settings: Settings = request.app.state.settings
    flow = available_providers(settings).get(provider)
    if flow is None:
        raise HTTPException(404, "OAuth provider not configured")
    state = secrets.token_urlsafe(32)
    try:
        async with request.app.state.sessions() as session:
            session.add(
                OAuthState(
                    token=state,
                    provider=provider,
                    expires_at=_now() + timedelta(minutes=STATE_TTL_MINUTES),
                )
            )
            await session.commit()
    except SQLAlchemyError:
        logger.exception("store oauth state failed provider=%s", provider)
        raise HTTPException(503, "Authentication service unavailable")
    response = RedirectResponse(flow.authorize_url(state), status_code=302)
    # 一次性 state 同时绑定到发起登录的浏览器（短期 HttpOnly Cookie）：
    # 回调必须携带同一值，防止任何第三方浏览器借合法 state 完成登录回调。
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=STATE_TTL_MINUTES * 60,
        path=STATE_COOKIE_PATH,
        **_cookie_params(settings),
    )
    return response


@router.get("/callback/{provider}")
async def callback(
    request: Request,
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    settings: Settings = request.app.state.settings
    flow = available_providers(settings).get(provider)
    if flow is None:
        return _login_error(settings, "oauth_failed")
    if error == "access_denied":
        return _state_cookie_error(settings, "canceled")
    if not code or not state:
        return _login_error(settings, "invalid_state")
    if request.cookies.get(STATE_COOKIE) != state:
        # 回调必须来自发起授权的同一浏览器；不匹配时既不创建会话，
        # 也不销毁库中 state（避免影响用户仍在进行的授权流程）。
        logger.warning("oauth callback state cookie mismatch provider=%s", provider)
        return _login_error(settings, "invalid_state")

    try:
        async with request.app.state.sessions() as session:
            consumed = (
                await session.execute(
                    delete(OAuthState)
                    .where(OAuthState.token == state, OAuthState.provider == provider)
                    .returning(OAuthState)
                )
            ).scalar_one_or_none()
            await session.commit()
    except SQLAlchemyError:
        logger.exception("consume oauth state failed provider=%s", provider)
        return _state_cookie_error(settings, "oauth_failed")
    if consumed is None:
        return _state_cookie_error(settings, "invalid_state")
    if consumed.expires_at < _now():
        return _state_cookie_error(settings, "expired")

    try:
        profile = await flow.fetch_profile(code)
    except OAuthFlowError:
        logger.warning("oauth exchange failed provider=%s", provider)
        return _state_cookie_error(settings, "oauth_failed")
    except Exception:
        logger.exception("unexpected oauth failure provider=%s", provider)
        return _state_cookie_error(settings, "oauth_failed")

    try:
        async with request.app.state.sessions() as session:
            user = (
                await session.execute(
                    select(PlatformUser).where(
                        PlatformUser.provider == profile.provider,
                        PlatformUser.provider_uid == profile.uid,
                    )
                )
            ).scalar_one_or_none()
            if user is None:
                # 白名单仅在"账号创建"时引导赋权（按稳定的 provider:provider_uid
                # 首次登录匹配，超管白名单优先）；已有账号不再套用白名单，角色以
                # 平台内设置为准，避免被降级的账号下次登录又被白名单恢复。
                account_key = f"{profile.provider}:{profile.uid}"
                if account_key in _superadmin_accounts(settings):
                    bootstrap_role = "superadmin"
                elif account_key in _admin_accounts(settings):
                    bootstrap_role = "admin"
                else:
                    bootstrap_role = "regular"
                user = PlatformUser(
                    provider=profile.provider,
                    provider_uid=profile.uid,
                    login=profile.login,
                    display_name=profile.display_name,
                    email=profile.email,
                    avatar_url=profile.avatar_url,
                    role=bootstrap_role,
                )
                session.add(user)
            else:
                # 已有账号仅刷新公开资料，保留已设置的角色
                user.login = profile.login
                user.display_name = profile.display_name
                user.email = profile.email
                user.avatar_url = profile.avatar_url
            await session.flush()
            if user.suspended_at is not None:
                await session.rollback()
                return _state_cookie_error(settings, "suspended")
            session_id = uuid_lib.uuid4()
            session.add(
                UserSession(
                    id=session_id,
                    user_id=user.id,
                    expires_at=_now() + timedelta(hours=settings.session_ttl_hours),
                )
            )
            await session.commit()
    except SQLAlchemyError:
        logger.exception("upsert user/session failed provider=%s", provider)
        return _state_cookie_error(settings, "oauth_failed")

    response = RedirectResponse(f"{settings.frontend_origin.rstrip('/')}/#console", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        str(session_id),
        max_age=settings.session_ttl_hours * 3600,
        path="/",
        **_cookie_params(settings),
    )
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH, **_cookie_params(settings))
    return response


@router.post("/logout")
async def logout(request: Request):
    settings: Settings = request.app.state.settings
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        try:
            session_id = uuid_lib.UUID(raw)
        except ValueError:
            session_id = None
        if session_id is not None:
            try:
                async with request.app.state.sessions() as session:
                    await session.execute(delete(UserSession).where(UserSession.id == session_id))
                    await session.commit()
            except SQLAlchemyError:
                # 服务端会话吊销失败时不允许假装退出成功：不清理 Cookie，
                # 返回可重试错误，前端会提示退出失败，用户保持在登录态。
                logger.exception("logout session delete failed")
                raise HTTPException(503, "退出失败：会话吊销未完成，请重试")
    response = JSONResponse({"data": {"ok": True}})
    response.delete_cookie(SESSION_COOKIE, path="/", **_cookie_params(settings))
    return response


@router.get("/me")
async def me(request: Request):
    settings: Settings = request.app.state.settings
    principal = await resolve_principal(request)
    if principal is not None:
        return {"data": principal.as_view()}
    if settings.auth_mode == "local":
        return {"data": local_principal().as_view()}
    # 区分“从未登录”与“会话已失效”：仅在已有会话失效时提示重新登录，
    # 首次访问的用户只会看到普通登录入口。
    if request.cookies.get(SESSION_COOKIE):
        return JSONResponse(
            status_code=401,
            content={
                "error": {"code": "SESSION_INVALID", "message": "会话已失效，请重新登录"},
                "request_id": request.state.request_id,
            },
        )
    return JSONResponse(
        status_code=401,
        content={
            "error": {"code": "NOT_AUTHENTICATED", "message": "Not authenticated"},
            "request_id": request.state.request_id,
        },
    )
