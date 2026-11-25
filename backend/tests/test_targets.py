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

@pytest.mark.parametrize("ssh_fails", [False, True])
async def test_explicit_probe_uses_only_selected_ssh_resource(monkeypatch, ssh_fails, tmp_path):
    from unittest.mock import AsyncMock, MagicMock, Mock
    from uuid import uuid4

    from autoeval.resources import targets

    target_id, resource_id = uuid4(), uuid4()
    target = SimpleNamespace(service_kind="local", base_url="https://model.example/v1",
                             credential_ref="ref", remote_model="test-model", id=target_id)
    resource = SimpleNamespace(id=resource_id)
    session = MagicMock()
    session.get = AsyncMock(side_effect=[target, resource])
    session.commit = AsyncMock()
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    settings = SimpleNamespace(allowed_model_hosts=["model.example"], secret_store_path=tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=settings, sessions=lambda: manager)), state=SimpleNamespace(request_id="test"))
    monkeypatch.setattr(targets.FileSecretStore, "get", lambda self, ref: "placeholder")
    connect = Mock(return_value=object())
    monkeypatch.setattr(targets, "connection_for", connect)
    remote = Mock(return_value=("matched", {}), side_effect=OSError() if ssh_fails else None)
    monkeypatch.setattr(targets, "probe_from_ssh", remote)
    monkeypatch.setattr(httpx, "AsyncClient", Mock(side_effect=AssertionError("local probe")))
    data = (await targets.check_connection(
        target_id, request, targets.ModelConnectionTestInput(ssh_resource_id=resource_id)))["data"]
    connect.assert_called_once_with(resource, settings)
    remote.assert_called_once_with(connect.return_value, target.base_url, "test-model", "placeholder")
    assert data["outcome"] == ("ssh_error" if ssh_fails else "matched")
    assert data["details"]["ssh_resource_id"] == str(resource_id)
    assert not data["generation_tested"]

@pytest.mark.parametrize(("code", "raw", "expected"), [
    (200, b'{"data":[{"id":"served"}]}', "matched"),
    (200, b'{"data":[]}', "model_not_found"),
    (302, b"", "upstream_error"),
    (200, b"{}", "invalid_response"),
])
def test_node_probe_requests_only_model_list(monkeypatch, code, raw, expected):
    from unittest.mock import MagicMock

    from autoeval.resources import model_list_probe

    factory = MagicMock()
    connection = factory.return_value
    response = connection.getresponse.return_value
    response.status = code
    response.read.return_value = raw
    monkeypatch.setattr(model_list_probe.http.client, "HTTPSConnection", factory)
    outcome, details = model_list_probe.check("https://local.example/v1", "served", "placeholder")
    assert outcome == expected
    connection.request.assert_called_once_with(
        "GET", "/v1/models", headers={"Authorization": "Bearer placeholder"}
    )
    connection.close.assert_called_once()
    assert "placeholder" not in repr(details)


def test_local_registration_accepts_executor_address():
    from autoeval.resources.targets import local_registration_url

    assert local_registration_url("http://localhost:8001/v1/") == "http://localhost:8001/v1"
