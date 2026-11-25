"""Identity auth: settings parsing, provider OAuth flows and local-mode endpoints."""

import os
import uuid as uuid_lib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.entrypoints.api import create_app
from autoeval.identity.models import OAuthState, PlatformUser, UserSession
from autoeval.identity.providers import (
    GitCodeProvider,
    GitHubProvider,
    OAuthFlowError,
    ProviderProfile,
    available_providers,
)
from autoeval.infrastructure.config import Settings
from autoeval.infrastructure.db import create_database


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _make_app(settings: Settings):
    app = create_app(settings)
    engine, sessions = create_database(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessions
    return app


def _github_provider() -> GitHubProvider:
    return GitHubProvider(
        "cid", "secret", "http://127.0.0.1:8000/api/autoeval/v1/auth/callback/github"
    )


def test_csv_env_lists_are_split():
    settings = _settings(
        oauth_enabled_providers="github, gitcode ",
        admin_accounts="github:alice,gitcode:bob",
    )
    assert settings.oauth_enabled_providers == ["github", "gitcode"]
    assert settings.admin_accounts == ["github:alice", "gitcode:bob"]


def test_csv_env_lists_parse_from_environment_source(monkeypatch):
    monkeypatch.setenv("AE_OAUTH_ENABLED_PROVIDERS", "github,gitcode")
    monkeypatch.setenv("AE_ADMIN_ACCOUNTS", "github:alice")
    settings = Settings(_env_file=None)
    assert settings.oauth_enabled_providers == ["github", "gitcode"]
    assert settings.admin_accounts == ["github:alice"]


def test_production_identity_config():
    # 免登录（local）模式仅限开发/测试；正式环境必须走 OAuth：
    # 缺少凭据或前端源/回调仍是本机地址都应拒绝启动
    with pytest.raises(ValueError):
        _settings(environment="production", auth_mode="local")
    with pytest.raises(ValueError):
        _settings(environment="production", auth_mode="oauth")
    with pytest.raises(ValueError):
        _settings(
            environment="production",
            auth_mode="oauth",
            github_client_id="gid",
            github_client_secret="gsec",
        )  # frontend_origin / redirect 默认仍是本机地址
    configured = _settings(
        environment="production",
        auth_mode="oauth",
        github_client_id="gid",
        github_client_secret="gsec",
        oauth_redirect_base="https://api.example.com",
        frontend_origin="https://app.example.com",
    )
    assert configured.auth_mode == "oauth"


def test_github_authorize_url():
    url = _github_provider().authorize_url("STATE123")
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "state=STATE123" in url
    assert (
        "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fautoeval%2Fv1%2Fauth%2Fcallback%2Fgithub"
        in url
    )
    assert "scope=read%3Auser+user%3Aemail" in url


def test_gitcode_authorize_url():
    flow = GitCodeProvider("cid", "secret", "http://cb/gitcode")
    url = flow.authorize_url("S1")
    assert url.startswith("https://gitcode.com/oauth/authorize?")
    assert "scope=all_user" in url
    assert "prompt=consent" in url
    assert "response_type=code" in url


async def test_github_exchange_and_profile_with_email_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            assert request.headers["Accept"] == "application/json"
            return httpx.Response(200, json={"access_token": "tok1"})
        if request.url.path == "/user":
            assert request.headers["Authorization"] == "Bearer tok1"
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "login": "alice",
                    "name": "Alice",
                    "email": None,
                    "avatar_url": "https://avatars/alice",
                },
            )
        if request.url.path == "/user/emails":
            return httpx.Response(
                200,
                json=[{"email": "a@example.com", "primary": True, "verified": True}],
            )
        return httpx.Response(404)

    flow = _github_provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await flow._exchange(client, "CODE")
        profile = await flow._profile(client, token)
    assert token == "tok1"
    assert profile.uid == "42"
    assert profile.login == "alice"
    assert profile.display_name == "Alice"
    assert profile.email == "a@example.com"


async def test_github_exchange_rejects_missing_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad_verification_code"})

    flow = _github_provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OAuthFlowError):
            await flow._exchange(client, "CODE")


async def test_gitcode_exchange_uses_form_encoding():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("Content-Type", "")
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "tok2"})

    flow = GitCodeProvider("cid", "sec", "http://cb/gitcode")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await flow._exchange(client, "CODE")
    assert token == "tok2"
    assert "application/x-www-form-urlencoded" in captured["content_type"]
    assert "grant_type=authorization_code" in captured["body"]
    assert "client_secret=sec" in captured["body"]


async def test_gitcode_profile_name_uses_login_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok2"
        return httpx.Response(
            200, json={"id": 7, "login": "bob", "email": "b@example.com", "avatar_url": None}
        )

    flow = GitCodeProvider("cid", "sec", "http://cb/gitcode")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        profile = await flow._profile(client, "tok2")
    assert profile.uid == "7"
    assert profile.display_name == "bob"
    assert profile.email == "b@example.com"


def test_available_providers_requires_complete_credentials():
    settings = _settings(
        github_client_id="gid",
        github_client_secret="gsec",
        gitcode_client_id="",
        gitcode_client_secret="",
        oauth_enabled_providers=["github", "gitcode"],
    )
    assert list(available_providers(settings)) == ["github"]
    assert available_providers(_settings(github_client_id="", github_client_secret="gsec")) == {}


async def test_me_local_mode_returns_local_operator():
    settings = _settings(auth_mode="local", oauth_enabled_providers=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)), base_url="http://test"
    ) as client:
        response = await client.get("/api/autoeval/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "id": "local-operator",
        "provider": "local",
        "login": "local-operator",
        "display_name": "本地操作员",
        "email": None,
        "avatar_url": None,
        "role": "admin",
    }


async def test_me_oauth_mode_without_cookie_is_401():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)), base_url="http://test"
    ) as client:
        response = await client.get("/api/autoeval/v1/auth/me")
    assert response.status_code == 401
    # 从未登录：不能提示"重新登录"，前端只显示普通登录入口
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_business_apis_require_session_in_oauth_mode():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)), base_url="http://test"
    ) as client:
        reports = await client.get("/api/autoeval/v1/reports")
        audit = await client.get("/api/autoeval/v1/audit-events")
        capabilities = await client.get("/api/autoeval/v1/system/capabilities")
    # 匿名读取报告 401；匿名查询审计 401；系统能力保持公开
    assert reports.status_code == 401
    assert audit.status_code == 401
    assert capabilities.status_code == 200


async def test_business_apis_bypass_guards_in_local_mode():
    settings = _settings(auth_mode="local")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)), base_url="http://test"
    ) as client:
        reports = await client.get("/api/autoeval/v1/reports")
    # 本地模式维持免登录开发流：不允许 401/403
    assert reports.status_code not in (401, 403)


async def test_providers_and_unknown_login_provider():
    settings = _settings(
        auth_mode="oauth",
        github_client_id="gid",
        github_client_secret="gsec",
        oauth_enabled_providers=["github"],
        frontend_origin="http://localhost:5173",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)), base_url="http://test"
    ) as client:
        providers = await client.get("/api/autoeval/v1/auth/providers")
        assert providers.json()["data"] == [{"provider": "github", "display_name": "GitHub"}]
        missing = await client.get("/api/autoeval/v1/auth/login/gitcode")
        assert missing.status_code == 404


async def test_callback_failures_redirect_with_friendly_errors():
    settings = _settings(
        auth_mode="oauth",
        github_client_id="gid",
        github_client_secret="gsec",
        oauth_enabled_providers=["github"],
        frontend_origin="http://localhost:5173",
    )
    app = _make_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        canceled = await client.get(
            "/api/autoeval/v1/auth/callback/github", params={"error": "access_denied"}
        )
        assert canceled.headers["location"] == "http://localhost:5173/#login?error=canceled"
        no_code = await client.get("/api/autoeval/v1/auth/callback/github", params={"state": "S"})
        assert no_code.headers["location"] == "http://localhost:5173/#login?error=invalid_state"


async def test_callback_requires_state_cookie_from_same_browser():
    settings = _settings(
        auth_mode="oauth",
        github_client_id="gid",
        github_client_secret="gsec",
        oauth_enabled_providers=["github"],
        frontend_origin="http://localhost:5173",
    )
    app = _make_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 未携带 state Cookie：拒绝且不发放会话 Cookie
        no_cookie = await client.get(
            "/api/autoeval/v1/auth/callback/github", params={"code": "c", "state": "s1"}
        )
        assert no_cookie.headers["location"] == "http://localhost:5173/#login?error=invalid_state"
        assert "ae_session" not in no_cookie.headers.get("set-cookie", "")
        # Cookie 与 state 不一致（跨浏览器）：同样拒绝
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies={"ae_oauth_state": "other-state"}
    ) as intruder:
        mismatch = await intruder.get(
            "/api/autoeval/v1/auth/callback/github", params={"code": "c", "state": "s2"}
        )
    assert mismatch.headers["location"] == "http://localhost:5173/#login?error=invalid_state"
    assert "ae_session" not in mismatch.headers.get("set-cookie", "")


async def test_logout_without_session_still_succeeds():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)), base_url="http://test"
    ) as client:
        response = await client.post("/api/autoeval/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["data"] == {"ok": True}


async def test_logout_returns_error_when_revocation_fails():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[])
    app = _make_app(settings)

    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise SQLAlchemyError("db failure")

    class BrokenContext:
        async def __aenter__(self):
            return BrokenSession()

        async def __aexit__(self, *args):
            return False

    class BrokenFactory:
        def __call__(self):
            return BrokenContext()

    app.state.sessions = BrokenFactory()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={"ae_session": str(uuid_lib.uuid4())},
    ) as client:
        response = await client.post("/api/autoeval/v1/auth/logout")
    # 吊销失败必须返回可重试错误，且不得清除 Cookie（不允许假装退出成功）
    assert response.status_code == 503
    assert "ae_session" not in (response.headers.get("set-cookie") or "")


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_logout_revokes_old_session_live():
    settings = _settings(
        auth_mode="oauth",
        oauth_enabled_providers=[],
        database_url="postgresql+asyncpg://autoeval:autoeval-dev-pw@127.0.0.1:5432/autoeval",
    )
    engine, sessions = create_database(settings)
    user = None
    session_id = uuid_lib.uuid4()
    async with sessions() as session:
        user = PlatformUser(
            provider="github",
            provider_uid=f"it-{uuid_lib.uuid4().hex[:12]}",
            login=f"tester-{uuid_lib.uuid4().hex[:8]}",
            display_name="Tester",
            role="regular",
        )
        session.add(user)
        await session.flush()
        session.add(
            UserSession(
                id=session_id, user_id=user.id, expires_at=datetime.now(UTC) + timedelta(hours=1)
            )
        )
        await session.commit()
    try:
        app = _make_app(settings)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(session_id)},
        ) as client:
            before = await client.get("/api/autoeval/v1/auth/me")
            assert before.status_code == 200
            assert before.json()["data"]["login"] == user.login
            out = await client.post("/api/autoeval/v1/auth/logout")
            assert out.status_code == 200
            assert "ae_session" in (out.headers.get("set-cookie") or "")
        # 用退出前的旧会话 Cookie 再访问：应为 401（旧会话已失效）
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(session_id)},
        ) as stale_client:
            stale = await stale_client.get("/api/autoeval/v1/auth/me")
        assert stale.status_code == 401
        async with sessions() as session:
            remaining = (
                await session.execute(select(UserSession).where(UserSession.id == session_id))
            ).scalar_one_or_none()
            assert remaining is None
    finally:
        async with sessions() as session:
            await session.execute(delete(PlatformUser).where(PlatformUser.id == user.id))
            await session.commit()
        await engine.dispose()


class _FakeProviderFlow:
    """绕过平台网络调用，直接返回固定用户资料。"""

    display_name = "GitHub"

    def __init__(self, profile: ProviderProfile, key: str = "github"):
        self.profile = profile
        self.key = key

    def authorize_url(self, state: str) -> str:
        return f"https://{self.key}.invalid/authorize?state={state}"

    async def fetch_profile(self, code: str) -> ProviderProfile:
        return self.profile


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_admin_whitelist_only_bootstraps_at_creation(monkeypatch):
    profile = ProviderProfile(
        provider="github",
        uid=f"uid-{uuid_lib.uuid4().hex[:12]}",
        login="tester-login",
        display_name="Tester",
        email="tester@example.com",
        avatar_url=None,
    )
    settings = _settings(
        auth_mode="oauth",
        oauth_enabled_providers=["github"],
        frontend_origin="http://localhost:5173",
        admin_accounts=[f"github:{profile.uid}"],
        database_url="postgresql+asyncpg://autoeval:autoeval-dev-pw@127.0.0.1:5432/autoeval",
    )
    monkeypatch.setattr(
        "autoeval.identity.routes.available_providers",
        lambda _s: {"github": _FakeProviderFlow(profile)},
    )
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    user_id = None

    async def seed_state(token: str):
        async with sessions() as session:
            session.add(
                OAuthState(
                    token=token,
                    provider="github",
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
            await session.commit()

    async def bootstrap_login(token: str):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_oauth_state": token},
        ) as client:
            response = await client.get(
                "/api/autoeval/v1/auth/callback/github", params={"code": "code", "state": token}
            )
        assert response.status_code == 302

    async def fetch_role():
        async with sessions() as session:
            return (
                await session.execute(select(PlatformUser.role).where(PlatformUser.id == user_id))
            ).scalar_one()

    try:
        # 首次登录：白名单命中的账号创建时引导为 admin
        first = uuid_lib.uuid4().hex
        await seed_state(first)
        await bootstrap_login(first)
        async with sessions() as session:
            created = (
                await session.execute(
                    select(PlatformUser).where(PlatformUser.provider_uid == profile.uid)
                )
            ).scalar_one()
            user_id = created.id
        assert await fetch_role() == "admin"

        # 模拟管理员将其降级为普通用户
        async with sessions() as session:
            user = (
                await session.execute(select(PlatformUser).where(PlatformUser.id == user_id))
            ).scalar_one()
            user.role = "regular"
            await session.commit()

        # 再次登录：白名单仍命中，但角色必须保持 regular（不被恢复为管理员）
        second = uuid_lib.uuid4().hex
        await seed_state(second)
        await bootstrap_login(second)
        assert await fetch_role() == "regular"
    finally:
        async with sessions() as session:
            if user_id is not None:
                await session.execute(delete(UserSession).where(UserSession.user_id == user_id))
            await session.execute(
                delete(PlatformUser).where(PlatformUser.provider_uid == profile.uid)
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_role_guards_on_business_apis_live():
    settings = _settings(
        auth_mode="oauth",
        oauth_enabled_providers=[],
        database_url="postgresql+asyncpg://autoeval:autoeval-dev-pw@127.0.0.1:5432/autoeval",
    )
    app = _make_app(settings)
    engine, sessions = create_database(settings)

    async def make_user(role: str):
        session_id = uuid_lib.uuid4()
        async with sessions() as session:
            user = PlatformUser(
                provider="github",
                provider_uid=f"g-{uuid_lib.uuid4().hex[:10]}",
                login=f"u-{uuid_lib.uuid4().hex[:8]}",
                display_name="Guard Tester",
                role=role,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserSession(
                    id=session_id,
                    user_id=user.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            await session.commit()
            return user, session_id

    regular, regular_session = await make_user("regular")
    admin, admin_session = await make_user("admin")
    try:
        # 匿名：报告 401
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as anon:
            assert (await anon.get("/api/autoeval/v1/reports")).status_code == 401
        # 普通用户：报告可读（授权范围内）；审计查询 403
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(regular_session)},
        ) as regular_client:
            assert (await regular_client.get("/api/autoeval/v1/reports")).status_code == 200
            assert (await regular_client.get("/api/autoeval/v1/audit-events")).status_code == 403
        # 管理员：审计查询 200
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as admin_client:
            assert (await admin_client.get("/api/autoeval/v1/audit-events")).status_code == 200
    finally:
        async with sessions() as session:
            await session.execute(
                delete(UserSession).where(UserSession.user_id.in_([regular.id, admin.id]))
            )
            await session.execute(
                delete(PlatformUser).where(PlatformUser.id.in_([regular.id, admin.id]))
            )
            await session.commit()
        await engine.dispose()


LIVE_DB = "postgresql+asyncpg://autoeval:autoeval-dev-pw@127.0.0.1:5432/autoeval"


def _oauth_app(monkeypatch, *, providers: dict[str, ProviderProfile]):
    settings = _settings(
        auth_mode="oauth",
        oauth_enabled_providers=list(providers),
        frontend_origin="http://localhost:5173",
        database_url=LIVE_DB,
    )
    monkeypatch.setattr(
        "autoeval.identity.routes.available_providers",
        lambda _s: {key: _FakeProviderFlow(profile, key=key) for key, profile in providers.items()},
    )
    return _make_app(settings)


async def _seed_state(sessions, token: str, provider: str, *, expires_in=5):
    async with sessions() as session:
        session.add(
            OAuthState(
                token=token,
                provider=provider,
                expires_at=datetime.now(UTC) + timedelta(minutes=expires_in),
            )
        )
        await session.commit()


async def _delete_user_by_uid(sessions, provider_uid: str):
    """清理测试账号：先吊销会话再删除用户（user_session 外键 RESTRICT）。"""
    async with sessions() as session:
        await session.execute(
            delete(UserSession).where(
                UserSession.user_id.in_(
                    select(PlatformUser.id).where(PlatformUser.provider_uid == provider_uid)
                )
            )
        )
        await session.execute(delete(PlatformUser).where(PlatformUser.provider_uid == provider_uid))
        await session.commit()


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_admin_whitelist_requires_stable_provider_uid(monkeypatch):
    # 白名单按 provider:provider_uid 匹配：登录名格式不再命中
    login_shaped = ProviderProfile(
        provider="github",
        uid=f"uid-{uuid_lib.uuid4().hex[:12]}",
        login="tester-login",
        display_name="Tester",
        email=None,
        avatar_url=None,
    )
    app = _oauth_app(monkeypatch, providers={"github": login_shaped})
    app.state.settings.admin_accounts = ["github:tester-login"]
    engine, sessions = create_database(app.state.settings)
    token = uuid_lib.uuid4().hex
    created_uid = None
    try:
        await _seed_state(sessions, token, "github")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_oauth_state": token},
        ) as client:
            response = await client.get(
                "/api/autoeval/v1/auth/callback/github",
                params={"code": "c", "state": token},
            )
        assert response.status_code == 302
        async with sessions() as session:
            created = (
                await session.execute(
                    select(PlatformUser).where(PlatformUser.provider_uid == login_shaped.uid)
                )
            ).scalar_one()
            created_uid = created.id
        # 登录名格式的白名单条目必须被忽略 → 普通用户
        assert created.role == "regular"

        # uid 格式条目命中：另一个新账号首登即管理员
        uid_shaped = ProviderProfile(
            provider="gitcode",
            uid=f"uid-{uuid_lib.uuid4().hex[:12]}",
            login="tester-login",
            display_name="Tester",
            email=None,
            avatar_url=None,
        )
        app2 = _oauth_app(monkeypatch, providers={"gitcode": uid_shaped})
        app2.state.settings.admin_accounts = [f"gitcode:{uid_shaped.uid}"]
        engine2, sessions2 = create_database(app2.state.settings)
        token2 = uuid_lib.uuid4().hex
        try:
            await _seed_state(sessions2, token2, "gitcode")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app2),
                base_url="http://test",
                cookies={"ae_oauth_state": token2},
            ) as client:
                response2 = await client.get(
                    "/api/autoeval/v1/auth/callback/gitcode",
                    params={"code": "c", "state": token2},
                )
            assert response2.status_code == 302
            async with sessions2() as session:
                created2 = (
                    await session.execute(
                        select(PlatformUser).where(PlatformUser.provider_uid == uid_shaped.uid)
                    )
                ).scalar_one()
                created2_id = created2.id
            assert created2.role == "admin"
        finally:
            async with sessions2() as session:
                await session.execute(delete(UserSession).where(UserSession.user_id == created2_id))
                await session.execute(delete(PlatformUser).where(PlatformUser.id == created2_id))
                await session.commit()
            await engine2.dispose()
    finally:
        async with sessions() as session:
            if created_uid is not None:
                await session.execute(delete(UserSession).where(UserSession.user_id == created_uid))
            await session.execute(
                delete(PlatformUser).where(PlatformUser.provider_uid == login_shaped.uid)
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_superadmin_whitelist_bootstraps_superadmin(monkeypatch):
    # AE_SUPERADMIN_ACCOUNTS 命中的账号首次登录即超管（优先于管理员白名单）
    profile = ProviderProfile(
        provider="gitcode",
        uid=f"uid-{uuid_lib.uuid4().hex[:12]}",
        login="first-owner",
        display_name="First Owner",
        email=None,
        avatar_url=None,
    )
    app = _oauth_app(monkeypatch, providers={"gitcode": profile})
    engine, sessions = create_database(app.state.settings)
    app.state.settings.superadmin_accounts = [f"gitcode:{profile.uid}"]
    app.state.settings.admin_accounts = [f"gitcode:{profile.uid}"]
    token = uuid_lib.uuid4().hex
    await _seed_state(sessions, token, "gitcode")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_oauth_state": token},
        ) as client:
            response = await client.get(
                "/api/autoeval/v1/auth/callback/gitcode",
                params={"code": "c", "state": token},
            )
        assert response.status_code == 302
        assert response.headers["location"] == "http://localhost:5173/#console"
        async with sessions() as session:
            role = (
                await session.execute(
                    select(PlatformUser.role).where(PlatformUser.provider_uid == profile.uid)
                )
            ).scalar_one()
        assert role == "superadmin"
    finally:
        await _delete_user_by_uid(sessions, profile.uid)
        await engine.dispose()


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_oauth_state_expired_never_creates_session(monkeypatch):
    profile = ProviderProfile(
        provider="github",
        uid=f"uid-{uuid_lib.uuid4().hex[:12]}",
        login="expired-user",
        display_name="Expired",
        email=None,
        avatar_url=None,
    )
    app = _oauth_app(monkeypatch, providers={"github": profile})
    engine, sessions = create_database(app.state.settings)
    token = uuid_lib.uuid4().hex
    await _seed_state(sessions, token, "github", expires_in=-1)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_oauth_state": token},
        ) as client:
            response = await client.get(
                "/api/autoeval/v1/auth/callback/github",
                params={"code": "c", "state": token},
            )
        assert response.status_code == 302
        assert response.headers["location"] == "http://localhost:5173/#login?error=expired"
        assert "ae_session" not in (response.headers.get("set-cookie") or "")
        # 过期回调不得创建用户或会话
        async with sessions() as session:
            user = (
                await session.execute(
                    select(PlatformUser).where(PlatformUser.provider_uid == profile.uid)
                )
            ).scalar_one_or_none()
            assert user is None
    finally:
        await engine.dispose()


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_oauth_state_cannot_be_reused(monkeypatch):
    profile = ProviderProfile(
        provider="github",
        uid=f"uid-{uuid_lib.uuid4().hex[:12]}",
        login="reuse-user",
        display_name="Reuse",
        email=None,
        avatar_url=None,
    )
    app = _oauth_app(monkeypatch, providers={"github": profile})
    engine, sessions = create_database(app.state.settings)
    token = uuid_lib.uuid4().hex
    await _seed_state(sessions, token, "github")
    session_count = None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_oauth_state": token},
        ) as client:
            first = await client.get(
                "/api/autoeval/v1/auth/callback/github",
                params={"code": "c", "state": token},
            )
        assert first.status_code == 302
        assert "http://localhost:5173/#console" == first.headers["location"]
        assert "ae_session" in (first.headers.get("set-cookie") or "")
        # 同一 state（同浏览器 Cookie）再次回调：必须拒绝且不再创建会话
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_oauth_state": token},
        ) as client:
            second = await client.get(
                "/api/autoeval/v1/auth/callback/github",
                params={"code": "c2", "state": token},
            )
        assert second.status_code == 302
        assert second.headers["location"] == "http://localhost:5173/#login?error=invalid_state"
        assert "ae_session" not in (second.headers.get("set-cookie") or "")
        async with sessions() as session:
            user = (
                await session.execute(
                    select(PlatformUser).where(PlatformUser.provider_uid == profile.uid)
                )
            ).scalar_one()
            session_count = (
                await session.execute(
                    select(func.count())
                    .select_from(UserSession)
                    .where(UserSession.user_id == user.id)
                )
            ).scalar_one()
        assert session_count == 1
    finally:
        await _delete_user_by_uid(sessions, profile.uid)
        await engine.dispose()


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_oauth_state_bound_to_requested_provider(monkeypatch):
    # state 是给 github 签发的，回调却在 gitcode 上使用：平台不匹配必须拒绝
    profile = ProviderProfile(
        provider="gitcode",
        uid=f"uid-{uuid_lib.uuid4().hex[:12]}",
        login="mismatch-user",
        display_name="Mismatch",
        email=None,
        avatar_url=None,
    )
    app = _oauth_app(monkeypatch, providers={"github": profile, "gitcode": profile})
    engine, sessions = create_database(app.state.settings)
    token = uuid_lib.uuid4().hex
    await _seed_state(sessions, token, "github")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_oauth_state": token},
        ) as client:
            response = await client.get(
                "/api/autoeval/v1/auth/callback/gitcode",
                params={"code": "c", "state": token},
            )
        assert response.status_code == 302
        assert response.headers["location"] == "http://localhost:5173/#login?error=invalid_state"
        assert "ae_session" not in (response.headers.get("set-cookie") or "")
    finally:
        await engine.dispose()


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_gitcode_successful_login_creates_session(monkeypatch):
    # 评审验收：两个平台分别验证成功登录（GitHub 由 whitelist 用例覆盖）
    profile = ProviderProfile(
        provider="gitcode",
        uid=f"uid-{uuid_lib.uuid4().hex[:12]}",
        login="gitcode-login",
        display_name="GitCode User",
        email=None,
        avatar_url=None,
    )
    app = _oauth_app(monkeypatch, providers={"gitcode": profile})
    engine, sessions = create_database(app.state.settings)
    token = uuid_lib.uuid4().hex
    await _seed_state(sessions, token, "gitcode")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_oauth_state": token},
        ) as client:
            response = await client.get(
                "/api/autoeval/v1/auth/callback/gitcode",
                params={"code": "c", "state": token},
            )
        assert response.status_code == 302
        assert response.headers["location"] == "http://localhost:5173/#console"
        assert "ae_session=" in (response.headers.get("set-cookie") or "")
        async with sessions() as session:
            user = (
                await session.execute(
                    select(PlatformUser).where(PlatformUser.provider_uid == profile.uid)
                )
            ).scalar_one()
            sessions_count = (
                await session.execute(
                    select(func.count())
                    .select_from(UserSession)
                    .where(UserSession.user_id == user.id)
                )
            ).scalar_one()
        assert user.provider == "gitcode"
        assert sessions_count == 1
    finally:
        await _delete_user_by_uid(sessions, profile.uid)
        await engine.dispose()


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL")
async def test_me_reports_session_invalid_for_stale_cookie():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=LIVE_DB)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)),
        base_url="http://test",
        cookies={"ae_session": str(uuid_lib.uuid4())},
    ) as client:
        response = await client.get("/api/autoeval/v1/auth/me")
    assert response.status_code == 401
    # 曾有会话（携带 Cookie 但已失效）：才提示"重新登录"，前端据此展示提示
    assert response.json()["error"]["code"] == "SESSION_INVALID"
