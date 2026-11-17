import importlib.util
import json
from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_budget_counts_actual_transport_attempts_and_excludes_keys(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "acceptance_guard",
        Path(__file__).parents[2] / "deploy/langfuse/automationbench_budget_guard.py",
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    calls = []

    async def original(client, request, **kwargs):
        calls.append(request)
        return httpx.Response(200, request=request, json={"ok": True})

    audit = tmp_path / "audit.jsonl"
    send = guard.guarded_send(
        original, limit=2, max_tokens=65536, model="deepseek-flash", effort="max", audit_path=audit
    )
    body = {
        "model": "deepseek-flash",
        "max_tokens": 65536,
        "reasoning_effort": "max",
        "thinking": {"type": "enabled"},
    }

    def request(payload):
        return httpx.Request(
            "POST",
            "https://api.deepseek.com/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer sk-test-never-log"},
        )

    assert (await send(None, request({**body, "max_tokens": 4096}))).status_code == 400
    assert len(calls) == 0
    assert (await send(None, request(body))).status_code == 200
    assert (await send(None, request(body))).status_code == 200
    assert (await send(None, request(body))).status_code == 400
    assert len(calls) == 2
    assert "sk-test" not in audit.read_text()
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert len([r for r in records if r["event"] == "request"]) == 2
