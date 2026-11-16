import httpx
import pytest

from autoeval.analysis_runtime import analyze


def payload():
    return {
        "base_url": "https://analysis.example/v1",
        "allowed_hosts": ["analysis.example"],
        "max_tokens": 2048,
        "prompt": "Analyze frozen evidence",
        "model": "glm-5.3",
        "api_key": "fixture-secret",
    }


def test_compatible_analysis_single_request_preserves_missing_usage():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        )

    result = analyze(payload(), transport=httpx.MockTransport(respond))
    assert len(calls) == 1
    assert str(calls[0].url) == "https://analysis.example/v1/chat/completions"
    assert result["usage"] == {"input_tokens": None, "output_tokens": None}


def test_compatible_analysis_does_not_retry_or_redirect():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://other.example"})

    assert analyze(payload(), transport=httpx.MockTransport(respond))["state"] == "failed"
    assert len(calls) == 1
    with pytest.raises(ValueError):
        analyze({**payload(), "allowed_hosts": []}, transport=httpx.MockTransport(respond))
    assert len(calls) == 1


def test_analysis_accepts_one_json_fence_but_keeps_closed_citations():
    import json

    from autoeval.analysis import validate_analysis_output

    body = {
        "summary": "已校验证据",
        "evidence_ids": ["run.summary"],
        "facts": [],
        "inferences": [],
        "recommended_actions": [],
    }
    raw = "```json\n" + json.dumps(body) + "\n```"
    assert validate_analysis_output(raw, {"run.summary": {}}) == body
    with pytest.raises(ValueError):
        validate_analysis_output("explanation\n" + raw, {"run.summary": {}})
    with pytest.raises(ValueError):
        validate_analysis_output(raw, {})


def test_short_citations_retain_original_attempt_identity_and_hash():
    import uuid

    from autoeval.analysis import build_analysis_input

    identifier = str(uuid.uuid4())
    result = build_analysis_input(
        report_id=uuid.uuid4(),
        report_sha256="a" * 64,
        snapshot_sha256="b" * 64,
        report_body={},
        snapshot_body={},
        short_case_ids=True,
        attempts=[
            {
                "attempt_id": identifier,
                "sha256": "c" * 64,
                "body": {"schema_version": "unified-case.v1"},
            }
        ],
    )
    assert result["schema_version"] == "analysis-input.v2"
    assert result["evidence_catalog"]["case.001"]["source_id"] == identifier
    assert result["evidence_catalog"]["case.001"]["sha256"] == "c" * 64


async def test_log_reader_uses_exact_owned_job_and_rejects_path_input():
    import json
    import uuid

    from autoeval.contracts import JobRef
    from autoeval.planning_transport import PlanningRemoteContainer

    adapter = object.__new__(PlanningRemoteContainer)
    adapter.container_id = "pinned-container"
    adapter.remote_dir = "/pinned-runtime"
    calls = []

    def command(args):
        calls.append(args)
        return json.dumps({"content": "fixture log", "truncated": False})

    adapter.command = command
    key = str(uuid.uuid4())
    result = await adapter.collect_log(JobRef(external_job_id=key, submission_key=key))
    assert result["content"] == "fixture log"
    assert calls[0][-1] == "/pinned-runtime/jobs/" + key + "/tool.log"
    with pytest.raises(ValueError):
        await adapter.collect_log(JobRef(external_job_id=key, submission_key="../other"))
    assert len(calls) == 1


async def test_analysis_dispatch_preserves_authorized_retry_number():
    import uuid
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from autoeval.dispatcher import deliver_once

    row = SimpleNamespace(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        kind="ANALYZE_REPORT",
        payload={"analysis_id": str(uuid.uuid4()), "retry_count": 1},
        state="pending",
        attempt_count=0,
    )

    class Session:
        @asynccontextmanager
        async def begin(self):
            yield

        async def scalar(self, statement):
            return row

    @asynccontextmanager
    async def sessions():
        yield Session()

    calls = []

    class Client:
        async def start_workflow(self, entry, request, **options):
            calls.append((request, options))

    assert await deliver_once(sessions, Client())
    assert calls[0][0]["retry_count"] == 1
    assert calls[0][1]["id"].endswith("/1")
    assert row.state == "delivered"
