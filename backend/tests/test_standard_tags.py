"""Repository tag labels are resolved to commits without changing saved inputs."""

from types import SimpleNamespace

import httpx
import pytest

from autoeval import standard_inputs


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 403])
async def test_tag_catalog_and_network_failure(monkeypatch, status):
    import subprocess

    def unavailable(*args, **kwargs):
        raise OSError("git unavailable in test")

    monkeypatch.setattr(subprocess, "run", unavailable)
    original = httpx.AsyncClient
    revision = "2f8f167a68f86ee022afcc7f2ae2b62bc2e6d2a2"

    def respond(request):
        assert request.url.path.endswith("/tags")
        return httpx.Response(status, json=[{"name": "2026-RP0", "commit": {"sha": revision}}])

    monkeypatch.setattr(
        standard_inputs.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await standard_inputs.repository_tags(
        SimpleNamespace(state=SimpleNamespace(request_id="test"))
    )
    assert result["data"] == (
        {"status": "available", "tags": [{"name": "2026-RP0", "revision": revision}]}
        if status == 200
        else {"status": "unavailable", "tags": []}
    )
