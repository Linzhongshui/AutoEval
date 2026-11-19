import json
import uuid
from types import SimpleNamespace

import pytest

from autoeval.infrastructure.config import Settings
from autoeval.reporting.langfuse_integration import build_plan, import_one, trace_view


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


def test_full_content_is_preserved_with_separate_stable_identity(tmp_path):
    data = artifact()
    trajectory = json.loads(data["files"]["agent/trajectory.json"])
    trajectory["steps"][1]["reasoning_content"] = "fixture reasoning"
    data["files"]["agent/trajectory.json"] = json.dumps(trajectory)
    _, structural = build_plan(data, tmp_path / "structural", "same-attempt")
    _, full = build_plan(data, tmp_path / "full", "same-attempt", mode="full")
    _, repeated = build_plan(data, tmp_path / "repeat", "same-attempt", mode="full")
    generation = next(span for span in full if span.role == "generation")
    assert generation.attributes["langfuse.observation.output"] == "answer"
    assert generation.attributes["atif.reasoning"] == "fixture reasoning"
    assert structural[0].trace_id != full[0].trace_id == repeated[0].trace_id
    assert isinstance(
        next(s for s in structural if s.role == "generation").attributes[
            "langfuse.observation.output"
        ],
        dict,
    )
    with pytest.raises(ValueError, match="content mode"):
        build_plan(data, tmp_path / "invalid", "same-attempt", mode="invalid")


@pytest.mark.asyncio
async def test_new_import_freezes_full_mode_before_configuration_changes(monkeypatch):
    from autoeval.reporting.langfuse_integration import archive_trace

    settings = Settings(
        langfuse_host="https://internal.example",
        langfuse_browser_url="https://browser.example",
        langfuse_project_id="project",
        langfuse_public_key="public",
        langfuse_secret_key="secret",
        _env_file=None,
    )
    assert settings.langfuse_content_mode == "full"
    saved = []
    session = SimpleNamespace(add=saved.append)
    monkeypatch.setattr("autoeval.reporting.langfuse_integration.write_manifest", lambda *args: None)
    await archive_trace(session, settings, uuid.uuid4(), uuid.uuid4(), artifact())
    settings.langfuse_content_mode = "structural"
    assert saved[0].content_mode == "full"


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


def test_import_configuration_requires_all_backend_fields():
    from autoeval.reporting.langfuse_integration import import_configured

    fields = {
        "langfuse_project_id": "project",
        "langfuse_host": "https://internal.example",
        "langfuse_browser_url": "https://browser.example",
        "langfuse_public_key": "public",
        "langfuse_secret_key": "secret",
    }
    assert import_configured(Settings(**fields, _env_file=None))
    for name in fields:
        assert not import_configured(Settings(**{**fields, name: ""}, _env_file=None))


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


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "partial", "unauthorized"])
async def test_import_confirmation_and_no_duplicate_send(monkeypatch, tmp_path, outcome):
    import httpx
    from harborstack.convert import export, scores

    row = SimpleNamespace(attempt_id=uuid.uuid4())
    _, plan = build_plan(artifact(), tmp_path, str(row.attempt_id))
    ids = [format(spec.span_id, "016x") for spec in plan]
    sent = []
    monkeypatch.setattr(export.Exporter, "send", lambda *args: sent.append(True))
    monkeypatch.setattr(scores, "backfill", lambda *args, **kwargs: [("reward", 201, "")])

    async def response(*args, **kwargs):
        return httpx.Response(
            401 if outcome == "unauthorized" else 200,
            request=httpx.Request("GET", "https://langfuse.example/api/public/v2/observations"),
            json={"data": [{"id": value} for value in (ids if outcome == "complete" else ids[:1])]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", response)
    settings = Settings(
        langfuse_host="https://langfuse.example",
        langfuse_browser_url="https://langfuse.example",
        _env_file=None,
    )
    if outcome == "complete":
        assert await import_one(row, settings, artifact()) == format(plan[0].trace_id, "032x")
    else:
        with pytest.raises((RuntimeError, httpx.HTTPStatusError)):
            await import_one(row, settings, artifact())
    assert not sent


def test_fixed_automation_tool_tree_and_inferred_timing(tmp_path):
    from pathlib import Path

    data = json.loads(
        (Path(__file__).parent / "fixtures/langfuse/automationbench-artifact.json").read_text()
    )
    rec, plan = build_plan(data, tmp_path, "fixture-attempt")
    tools = [s for s in plan if s.role == "tool"]
    assert len(tools) == 1 and tools[0].name == "tool.read_record"
    assert plan[tools[0].parent].role == "generation"
    assert rec.reward == 1
    assert tools[0].attributes["atif.timing_source"].startswith("inferred")
