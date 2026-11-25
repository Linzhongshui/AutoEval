from types import SimpleNamespace

import httpx
import pytest

from autoeval.resources.targets import probe_model_list, service_kind, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://api.deepseek.com",
        "https://evil.invalid",
        "https://user:pass@api.deepseek.com",
        "https://api.deepseek.com/?key=secret",
    ],
)
def test_endpoint_must_be_explicitly_allowed(url):
    with pytest.raises(ValueError):
        validate_url(url, ["api.deepseek.com"])


async def test_model_list_does_not_generate_and_errors_do_not_echo_secret():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/models"
        return httpx.Response(200, json={"data": [{"id": "test-model"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome, details = await probe_model_list(
            "https://api.deepseek.com", "test-model", "placeholder", client
        )
    assert outcome == "matched"
    assert "placeholder" not in str(details)


async def test_failed_auth_does_not_expose_upstream_body():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="sensitive-placeholder")
        )
    ) as client:
        outcome, details = await probe_model_list(
            "https://api.deepseek.com", "test-model", "placeholder", client
        )
    assert outcome == "upstream_error"
    assert details == {"http_status": 401}

@pytest.mark.parametrize(("kind", "url", "expected"), [
    ("official", "https://vendor.example/v1", "official"),
    ("local", "https://inference.example/v1", "local"),
    (None, "https://api.deepseek.com/v1", "official"),
    (None, "https://api.deepseek.com.example/v1", None),
])
def test_service_source_for_existing_bindings(kind, url, expected):
    assert service_kind(SimpleNamespace(service_kind=kind, base_url=url)) == expected

async def test_local_service_probe_stops_before_any_network_request(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from uuid import uuid4

    from fastapi import HTTPException

    from autoeval.resources.targets import check_connection

    session = AsyncMock()
    session.get.return_value = SimpleNamespace(service_kind="local")
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    state = SimpleNamespace(settings=object(), sessions=lambda: manager)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    client = Mock(side_effect=AssertionError("unexpected platform HTTP client"))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    with pytest.raises(HTTPException) as raised:
        await check_connection(uuid4(), request)
    assert raised.value.status_code == 409
    client.assert_not_called()
