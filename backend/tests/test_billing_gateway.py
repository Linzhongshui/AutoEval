import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from autoeval.billing_transport import execution_route, route_compilation


def test_private_budget_routing_and_no_fallback(tmp_path):
    run = uuid.uuid4()
    target = uuid.uuid4()
    path = tmp_path / "routing.json"
    path.write_text(
        json.dumps(
            {
                "private_base_url": "http://172.17.0.99:18080",
                "grants": [
                    {
                        "target_id": str(target),
                        "dataset": "GPQA",
                        "section": "evaluation",
                        "execution_token": "private-ticket",
                    }
                ],
            }
        )
    )
    settings = SimpleNamespace(billing_execution_config=path)
    route = execution_route(settings, run, target, "GPQA")
    assert route["base_url"] == f"http://172.17.0.99:18080/runs/{run}/v1"
    compiled = {
        "config": {"subcommand": "llm_accuracy", "params": {"url": "https://api.deepseek.com/v1"}}
    }
    assert route_compilation(compiled, route)["config"]["params"]["url"] == route["base_url"]
    assert compiled["config"]["params"]["url"] == "https://api.deepseek.com/v1"
    with pytest.raises(ValueError, match="fallback forbidden"):
        execution_route(settings, run, target, "AutomationBench")
    assert execution_route(SimpleNamespace(), run, target, "GPQA") is None


@pytest.mark.asyncio
async def test_gateway_rejects_unscoped_and_expired_tokens_without_model_calls(tmp_path):
    import httpx

    from autoeval.billing_gateway import create_gateway

    path = tmp_path / "gateway.json"
    token = "test-only"
    path.write_text(
        json.dumps(
            {
                "deadline": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                "grants": [{"token_sha256": hashlib.sha256(token.encode()).hexdigest()}],
            }
        )
    )
    app = create_gateway(path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        route = f"/runs/{uuid.uuid4()}/v1/chat/completions"
        assert (await c.post(route, json={})).status_code == 401
        assert (
            await c.post(route, json={}, headers={"Authorization": "Bearer " + token})
        ).status_code == 403
    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_usage", [False, True])
async def test_stream_relays_live_and_commits_before_done(monkeypatch, missing_usage):
    from unittest.mock import AsyncMock

    import httpx

    import autoeval.billing_stream as stream

    wire = b'data: {"choices":[{"delta":{"content":"answer"}}]}\n\n'
    if not missing_usage:
        wire += b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2}}\n\n'
    wire += b"data: [DONE]\n\n"
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=wire))
    monkeypatch.setattr(
        stream.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    settled = AsyncMock(return_value="unresolved" if missing_usage else "settled")
    monkeypatch.setattr(stream, "finish_request", settled)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def begin(self):
            return self

    failed = []
    iterator = stream.relay_stream(
        Session,
        uuid.uuid4(),
        {},
        "https://provider.invalid/v1",
        "test-only",
        {},
        5,
        False,
        lambda: failed.append(True),
    )
    first = await anext(iterator)
    assert b"answer" in first and settled.await_count == 0
    if missing_usage:
        with pytest.raises(ValueError, match="usage_unknown"):
            await anext(iterator)
    else:
        assert b"[DONE]" in await anext(iterator)
        assert settled.await_count == 1
        assert settled.await_args.args[2]["completion_tokens"] == 2
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)
    assert not failed


def test_budget_mode_blocks_legacy_paid_entrypoints(tmp_path):
    from fastapi.testclient import TestClient

    from autoeval.api import create_app
    from autoeval.config import Settings

    client = TestClient(create_app(Settings(billing_execution_config=tmp_path / "private.json", enforce_task_budget=True)))
    for path in ("/runs", "/aisbench-monitored/runs", "/planning/probes"):
        response = client.post("/api/autoeval/v1" + path, json={})
        assert response.status_code == 409
        assert "evaluation-tasks" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unexpected_failure_latches_proxy_closed(tmp_path):
    import httpx

    from autoeval.billing_gateway import create_gateway

    path = tmp_path / "gateway.json"
    token = "test-scoped-token"
    path.write_text(
        json.dumps(
            {
                "deadline": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                "grants": [{"token_sha256": hashlib.sha256(token.encode()).hexdigest()}],
            }
        )
    )
    app = create_gateway(path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        endpoint = f"/runs/{uuid.uuid4()}/v1/chat/completions"
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        assert (await client.post(endpoint, headers=headers, content=b"{")).status_code == 503
        assert app.state.accounting_failed is True
        assert (await client.post(endpoint, headers=headers, json={})).status_code == 503
    await app.state.engine.dispose()

def test_default_budget_policy_does_not_block_probe_validation(tmp_path):
    from fastapi.testclient import TestClient

    from autoeval.api import create_app
    from autoeval.config import Settings

    client = TestClient(create_app(Settings(billing_execution_config=tmp_path / "missing-private.json")))
    response = client.post('/api/autoeval/v1/planning/probes', json={})
    assert response.status_code == 422
    assert 'Active budget' not in response.text
