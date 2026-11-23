"""Identity auth: settings parsing, provider OAuth flows and local-mode endpoints."""

import httpx
import pytest

from autoeval.entrypoints.api import create_app
from autoeval.identity.providers import (
    GitCodeProvider,
    GitHubProvider,
    OAuthFlowError,
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


def test_production_requires_oauth_mode():
    with pytest.raises(ValueError):
        _settings(environment="production", auth_mode="local")
    settings = _settings(environment="production", auth_mode="oauth")
    assert settings.auth_mode == "oauth"


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


async def test_logout_without_session_still_succeeds():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)), base_url="http://test"
    ) as client:
        response = await client.post("/api/autoeval/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["data"] == {"ok": True}
