import json
import uuid
from types import SimpleNamespace

import pytest

from autoeval.config import Settings
from autoeval.langfuse_integration import build_plan, import_one, trace_view


def artifact():
    return {
        "trial_name": "task__agent__model__1",
        "files": {
            "agent/trajectory.json": json.dumps(
                {
                    "session_id": "session",
                    "steps": [
                        {
                            "step_id": 1,
                            "source": "user",
                            "message": "question",
                            "timestamp": "2026-11-16T00:00:00Z",
                        },
                        {
                            "step_id": 2,
                            "source": "agent",
                            "message": "answer",
                            "model_name": "model",
                            "timestamp": "2026-11-16T00:00:01Z",
                        },
                    ],
                }
            ),
            "verifier/reward.txt": "1",
        },
    }


def test_plan_identity_and_score(tmp_path):
    rec, first = build_plan(artifact(), tmp_path / "one", "attempt-1")
    _, second = build_plan(artifact(), tmp_path / "two", "attempt-1")
    _, different = build_plan(artifact(), tmp_path / "three", "attempt-2")
    assert rec.reward == 1
    assert first[0].trace_id == second[0].trace_id
    assert first[0].trace_id != different[0].trace_id
    assert any(s.role == "generation" for s in first)


def test_artifact_path_rejected(tmp_path):
    data = artifact()
    data["files"]["../secret"] = "bad"
    with pytest.raises(ValueError):
        build_plan(data, tmp_path, "attempt")


def test_link_requires_confirmation():
    settings = Settings(langfuse_browser_url="https://langfuse.example", _env_file=None)
    row = SimpleNamespace(
        status="failed", langfuse_project="project", trace_id="a" * 32, error_code="FAILED"
    )
    assert trace_view(row, settings)["trace_url"] is None
    row.status = "succeeded"
    assert trace_view(row, settings)["trace_url"].endswith("/project/project/traces/" + "a" * 32)
    assert trace_view(None, settings)["trace_status"] == "unsupported"


@pytest.mark.asyncio
async def test_query_failure_never_sends(monkeypatch):
    import httpx
    from harborstack.convert.export import Exporter

    sent = []
    monkeypatch.setattr(Exporter, "send", lambda *args: sent.append(True))

    async def failure(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "get", failure)
    settings = Settings(
        langfuse_host="https://langfuse.example",
        langfuse_browser_url="https://langfuse.example",
        _env_file=None,
    )
    with pytest.raises(httpx.ConnectError):
        await import_one(SimpleNamespace(attempt_id=uuid.uuid4()), settings, artifact())
    assert not sent
