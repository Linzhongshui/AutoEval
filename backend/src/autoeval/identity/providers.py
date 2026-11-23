"""OAuth2 authorization-code providers for GitHub and GitCode; secrets stay server-side."""

import urllib.parse
from dataclasses import dataclass

import httpx

from autoeval.infrastructure.config import Settings

CALLBACK_PATH = "/api/autoeval/v1/auth/callback/"


class OAuthFlowError(RuntimeError):
    """Authorization exchange or profile fetch failed; exposed as oauth_failed."""


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    uid: str
    login: str
    display_name: str
    email: str | None
    avatar_url: str | None


class OAuthProvider:
    key: str = ""
    display_name: str = ""
    authorize_endpoint: str = ""
    token_endpoint: str = ""
    profile_endpoint: str = ""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def extra_authorize_params(self) -> dict:
        return {}

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
            **self.extra_authorize_params(),
        }
        return f"{self.authorize_endpoint}?{urllib.parse.urlencode(params)}"

    async def fetch_profile(self, code: str) -> ProviderProfile:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token = await self._exchange(client, code)
            return await self._profile(client, token)

    async def _exchange(self, client: httpx.AsyncClient, code: str) -> str:
        raise NotImplementedError

    async def _profile(self, client: httpx.AsyncClient, token: str) -> ProviderProfile:
        raise NotImplementedError

    @staticmethod
    def _require_token(payload: dict) -> str:
        token = payload.get("access_token")
        if not token:
            raise OAuthFlowError("access_token missing in token response")
        return token


class GitHubProvider(OAuthProvider):
    key = "github"
    display_name = "GitHub"
    authorize_endpoint = "https://github.com/login/oauth/authorize"
    token_endpoint = "https://github.com/login/oauth/access_token"
    profile_endpoint = "https://api.github.com/user"
    emails_endpoint = "https://api.github.com/user/emails"

    def extra_authorize_params(self) -> dict:
        return {"scope": "read:user user:email"}

    async def _exchange(self, client: httpx.AsyncClient, code: str) -> str:
        response = await client.post(
            self.token_endpoint,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if response.is_error:
            raise OAuthFlowError(f"GitHub token exchange failed: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthFlowError("GitHub token response was not JSON") from exc
        return self._require_token(payload)

    async def _profile(self, client: httpx.AsyncClient, token: str) -> ProviderProfile:
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(self.profile_endpoint, headers=headers)
        if response.is_error:
            raise OAuthFlowError(f"GitHub profile fetch failed: HTTP {response.status_code}")
        body = response.json()
        email = body.get("email") or None
        if not email:
            emails = await client.get(self.emails_endpoint, headers=headers)
            if emails.is_success:
                for entry in emails.json():
                    if entry.get("primary") and entry.get("verified"):
                        email = entry.get("email")
                        break
        return ProviderProfile(
            provider=self.key,
            uid=str(body["id"]),
            login=body["login"],
            display_name=body.get("name") or body["login"],
            email=email,
            avatar_url=body.get("avatar_url"),
        )


class GitCodeProvider(OAuthProvider):
    key = "gitcode"
    display_name = "GitCode"
    authorize_endpoint = "https://gitcode.com/oauth/authorize"
    token_endpoint = "https://gitcode.com/oauth/token"
    profile_endpoint = "https://api.gitcode.com/api/v5/user"

    def extra_authorize_params(self) -> dict:
        # prompt=consent：每次登录都强制 GitCode 重新弹出授权确认页，
        # 避免平台记住的旧授权让再次登录直接静默通过。
        return {"scope": "all_user", "prompt": "consent"}

    async def _exchange(self, client: httpx.AsyncClient, code: str) -> str:
        # GitCode 要求表单编码（非 JSON），httpx data=dict 自动设置该 Content-Type。
        response = await client.post(
            self.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if response.is_error:
            raise OAuthFlowError(f"GitCode token exchange failed: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthFlowError("GitCode token response was not JSON") from exc
        return self._require_token(payload)

    async def _profile(self, client: httpx.AsyncClient, token: str) -> ProviderProfile:
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(self.profile_endpoint, headers=headers)
        if response.is_error:
            raise OAuthFlowError(f"GitCode profile fetch failed: HTTP {response.status_code}")
        body = response.json()
        return ProviderProfile(
            provider=self.key,
            uid=str(body["id"]),
            login=body["login"],
            display_name=body.get("name") or body["login"],
            email=body.get("email"),
            avatar_url=body.get("avatar_url"),
        )


def available_providers(settings: Settings) -> dict[str, OAuthProvider]:
    """Providers with complete credentials and present in the enabled list."""
    enabled = set(settings.oauth_enabled_providers)
    callback_base = f"{settings.oauth_redirect_base.rstrip('/')}{CALLBACK_PATH}"
    providers: dict[str, OAuthProvider] = {}
    if "github" in enabled:
        client_id = settings.github_client_id.get_secret_value()
        client_secret = settings.github_client_secret.get_secret_value()
        if client_id and client_secret:
            providers["github"] = GitHubProvider(client_id, client_secret, f"{callback_base}github")
    if "gitcode" in enabled:
        client_id = settings.gitcode_client_id.get_secret_value()
        client_secret = settings.gitcode_client_secret.get_secret_value()
        if client_id and client_secret:
            providers["gitcode"] = GitCodeProvider(
                client_id, client_secret, f"{callback_base}gitcode"
            )
    return providers
