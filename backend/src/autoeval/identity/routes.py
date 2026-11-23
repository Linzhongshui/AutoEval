"""OAuth login / logout / current-user endpoints for GitHub and GitCode."""

import logging
import secrets
import uuid as uuid_lib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.identity.models import OAuthState, PlatformUser, UserSession
from autoeval.identity.providers import OAuthFlowError, available_providers
from autoeval.infrastructure.config import Settings

logger = logging.getLogger("autoeval.identity")
router = APIRouter(prefix="/api/autoeval/v1/auth", tags=["auth"])

SESSION_COOKIE = "ae_session"
STATE_TTL_MINUTES = 5


def _now() -> datetime:
    return datetime.now(UTC)


def _cookie_params(settings: Settings) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.environment == "production",
        "path": "/",
    }


def _login_error(settings: Settings, code: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.frontend_origin.rstrip('/')}/#login?error={code}", status_code=302
    )


def _admin_accounts(settings: Settings) -> set[str]:
    return {entry.strip() for entry in settings.admin_accounts if ":" in entry}


def _user_view(user: PlatformUser) -> dict:
    return {
        "id": str(user.id),
        "provider": user.provider,
        "login": user.login,
        "display_name": user.display_name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "role": user.role,
    }


def _local_operator() -> dict:
    return {
        "id": "local-operator",
        "provider": "local",
        "login": "local-operator",
        "display_name": "本地操作员",
        "email": None,
        "avatar_url": None,
        "role": "admin",
    }


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
    return RedirectResponse(flow.authorize_url(state), status_code=302)


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
        return _login_error(settings, "canceled")
    if not code or not state:
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
        return _login_error(settings, "oauth_failed")
    if consumed is None:
        return _login_error(settings, "invalid_state")
    if consumed.expires_at < _now():
        return _login_error(settings, "expired")

    try:
        profile = await flow.fetch_profile(code)
    except OAuthFlowError:
        logger.warning("oauth exchange failed provider=%s", provider)
        return _login_error(settings, "oauth_failed")
    except Exception:
        logger.exception("unexpected oauth failure provider=%s", provider)
        return _login_error(settings, "oauth_failed")

    role = (
        "admin" if f"{profile.provider}:{profile.login}" in _admin_accounts(settings) else "regular"
    )
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
                user = PlatformUser(
                    provider=profile.provider,
                    provider_uid=profile.uid,
                    login=profile.login,
                    display_name=profile.display_name,
                    email=profile.email,
                    avatar_url=profile.avatar_url,
                    role=role,
                )
                session.add(user)
            else:
                user.login = profile.login
                user.display_name = profile.display_name
                user.email = profile.email
                user.avatar_url = profile.avatar_url
                if role == "admin" and user.role != "admin":
                    user.role = "admin"
            await session.flush()
            if user.suspended_at is not None:
                await session.rollback()
                return _login_error(settings, "suspended")
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
        return _login_error(settings, "oauth_failed")

    response = RedirectResponse(f"{settings.frontend_origin.rstrip('/')}/#console", status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        str(session_id),
        max_age=settings.session_ttl_hours * 3600,
        **_cookie_params(settings),
    )
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
                logger.warning("logout session delete failed", exc_info=True)
    response = JSONResponse({"data": {"ok": True}})
    response.delete_cookie(SESSION_COOKIE, **_cookie_params(settings))
    return response


@router.get("/me")
async def me(request: Request):
    settings: Settings = request.app.state.settings
    raw = request.cookies.get(SESSION_COOKIE)
    user = None
    if raw:
        try:
            session_id = uuid_lib.UUID(raw)
        except ValueError:
            session_id = None
        if session_id is not None:
            try:
                async with request.app.state.sessions() as session:
                    row = (
                        await session.execute(
                            select(PlatformUser, UserSession)
                            .join(UserSession, UserSession.user_id == PlatformUser.id)
                            .where(
                                UserSession.id == session_id,
                                UserSession.revoked_at.is_(None),
                                UserSession.expires_at > _now(),
                                PlatformUser.suspended_at.is_(None),
                            )
                        )
                    ).first()
                user = row[0] if row is not None else None
            except SQLAlchemyError:
                logger.exception("session lookup failed")
                raise HTTPException(503, "Authentication service unavailable")
    if user is not None:
        return {"data": _user_view(user)}
    if settings.auth_mode == "local":
        return {"data": _local_operator()}
    raise HTTPException(401, "Not authenticated")
