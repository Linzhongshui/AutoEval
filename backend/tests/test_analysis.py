import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from autoeval.analysis import (
    ReportAnalysis,
    analysis_is_configured,
    analysis_status_for,
    build_analysis_input,
    enqueue_analysis,
    retry_existing_analysis,
    validate_analysis_output,
)
from autoeval.analysis_activity import build_analysis_result
from autoeval.api import create_app
from autoeval.config import Settings

ATTEMPT_ID = uuid.uuid4()
CATALOG = {
    "run.summary": {"kind": "run_summary", "sha256": "a" * 64},
    f"attempt:{ATTEMPT_ID}": {"kind": "case_attempt", "sha256": "b" * 64},
    "baseline.comparison": {"kind": "baseline_comparison", "sha256": "c" * 64},
}


def test_model_output_accepts_only_server_issued_evidence_aliases():
    output = validate_analysis_output(
        json.dumps(
            {
                "summary": "The failed attempt explains the incomplete run.",
                "evidence_ids": ["run.summary", f"attempt:{ATTEMPT_ID}"],
                "facts": [{"statement": "The run is incomplete", "evidence_ids": ["run.summary"]}],
                "inferences": [{"statement": "A failed attempt may explain it", "evidence_ids": [f"attempt:{ATTEMPT_ID}"]}],
                "recommended_actions": ["Inspect the failed response before rerunning."],
            }
        ),
        CATALOG,
    )
    assert output["evidence_ids"] == ["run.summary", f"attempt:{ATTEMPT_ID}"]


@pytest.mark.parametrize(
    "evidence_ids",
    [
        ["run.summary", "run.summary"],
        ["attempt:00000000-0000-0000-0000-000000000001"],
        ["baseline.comparison", "configuration"],
        [],
    ],
)
def test_model_output_rejects_duplicate_unknown_or_empty_citations(evidence_ids):
    with pytest.raises(ValueError):
        validate_analysis_output(
            {"summary": "Conclusion", "evidence_ids": evidence_ids, "recommended_actions": []},
            CATALOG,
        )


@pytest.mark.parametrize(
    "body",
    [
        {"summary": "ok", "evidence_ids": ["run.summary"]},
        {
            "summary": "ok",
            "evidence_ids": ["run.summary"],
            "recommended_actions": [],
            "release_decision": "approved",
        },
        {"summary": "", "evidence_ids": ["run.summary"], "recommended_actions": []},
        {"summary": "ok", "evidence_ids": "run.summary", "recommended_actions": []},
    ],
)
def test_model_output_has_a_closed_schema(body):
    with pytest.raises(ValueError):
        validate_analysis_output(body, CATALOG)


def test_evidence_input_is_hash_bound_and_contains_no_credentials():
    report_id = uuid.uuid4()
    attempt = {
        "attempt_id": str(ATTEMPT_ID),
        "sha256": "b" * 64,
        "body": {
            "schema_version": "case-evidence.v1",
            "attempt_id": str(ATTEMPT_ID),
            "response": "model answer",
        },
    }
    body = {
        "schema_version": "gpqa-report.v1",
        "run_id": str(uuid.uuid4()),
        "summary": {"accuracy": 50.0},
    }
    snapshot = {"target_id": str(uuid.uuid4()), "api_key": "must-not-be-copied"}
    evidence_input = build_analysis_input(
        report_id=report_id,
        report_sha256="a" * 64,
        snapshot_sha256="d" * 64,
        report_body=body,
        snapshot_body=snapshot,
        attempts=[attempt],
        baseline_comparison={"status": "incomparable"},
        baseline_comparison_sha256="c" * 64,
    )
    assert set(evidence_input["evidence_catalog"]) == {
        "run.summary",
        f"attempt:{ATTEMPT_ID}",
        "baseline.comparison",
    }
    serialized = json.dumps(evidence_input)
    assert "must-not-be-copied" not in serialized
    assert "api_key" not in serialized
    with pytest.raises(ValueError):
        build_analysis_input(
            report_id=report_id,
            report_sha256="a" * 64,
            snapshot_sha256="d" * 64,
            report_body=body,
            snapshot_body=snapshot,
            attempts=[{**attempt, "body": {**attempt["body"], "attempt_id": str(uuid.uuid4())}}],
        )


class FakeSession:
    def __init__(self, report, target, resource, existing=None):
        self.report = report
        self.target = target
        self.resource = resource
        self.existing = existing
        self.added = []
        self.scalar_calls = 0

    async def scalar(self, _query):
        self.scalar_calls += 1
        return self.report if self.scalar_calls == 1 else self.existing

    async def get(self, model, _identifier):
        return {"TargetBinding": self.target, "ResourceBinding": self.resource}[model.__name__]

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass


def configured_settings():
    return SimpleNamespace(
        analysis_target_id=uuid.uuid4(),
        analysis_resource_id=uuid.uuid4(),
        analysis_activity_queue="demo.result.v1",
        analysis_workflow_queue="demo.workflow.v1",
    )


async def test_enqueue_is_idempotent_and_snapshot_contains_no_credential_ref():
    settings = configured_settings()
    report = SimpleNamespace(
        id=uuid.uuid4(), run_id=uuid.uuid4(), sha256="a" * 64, snapshot_sha256="d" * 64
    )
    snapshot = SimpleNamespace(sha256="d" * 64)
    target = SimpleNamespace(
        id=settings.analysis_target_id,
        model_version_id=uuid.uuid4(),
        base_url="https://api.deepseek.com",
        remote_model="deepseek-flash",
        credential_ref="0" * 32,
    )
    resource = SimpleNamespace(
        id=settings.analysis_resource_id, container_id="container", image_id="image"
    )
    session = FakeSession(report, target, resource)
    job, created = await enqueue_analysis(
        session,
        settings,
        report,
        snapshot,
        trigger="report_created",
        baseline_comparison={"status": "missing"},
    )
    assert created is True
    assert isinstance(job, ReportAnalysis)
    assert "credential_ref" not in job.target_snapshot
    assert "api_key" not in job.target_snapshot
    assert job.baseline_comparison == {"status": "missing"}
    assert len(job.baseline_comparison_sha256) == 64
    assert len(session.added) == 2
    assert session.added[1].kind == "ANALYZE_REPORT"

    duplicate = FakeSession(report, target, resource, existing=job)
    same, created = await enqueue_analysis(
        duplicate, settings, report, snapshot, trigger="manual_retry"
    )
    assert same is job and created is False
    assert duplicate.added == []


def test_analysis_capability_requires_two_separate_explicit_bindings():
    settings = configured_settings()
    assert analysis_is_configured(settings)
    settings.analysis_resource_id = None
    assert not analysis_is_configured(settings)


class RetrySession:
    def __init__(self, job):
        self.job = job
        self.added = []

    async def scalar(self, _query):
        return self.job

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass


async def test_failed_analysis_retries_same_job_at_most_once():
    settings = configured_settings()
    job = ReportAnalysis(
        id=uuid.uuid4(),
        report_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        state="failed",
        trigger="report_created",
        retry_count=0,
        report_sha256="a" * 64,
        snapshot_sha256="d" * 64,
        target_snapshot={},
        evidence_catalog={},
        error_code="INVALID_MODEL_OUTPUT",
    )
    session = RetrySession(job)
    retried, created = await retry_existing_analysis(session, settings, job)
    assert retried is job and created is True
    assert job.state == "queued" and job.retry_count == 1
    assert job.error_code is None
    assert len(session.added) == 1
    assert session.added[0].dedup_key == f"analysis:{job.id}:manual-retry"
    assert session.added[0].payload["retry_count"] == 1

    job.state = "failed"
    duplicate = RetrySession(job)
    same, created = await retry_existing_analysis(duplicate, settings, job)
    assert same is job and created is False
    assert duplicate.added == []


async def test_unresolved_analysis_is_never_retried_blindly():
    settings = configured_settings()
    job = ReportAnalysis(
        id=uuid.uuid4(),
        report_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        state="unresolved",
        trigger="report_created",
        retry_count=0,
        report_sha256="a" * 64,
        snapshot_sha256="d" * 64,
        target_snapshot={},
        evidence_catalog={},
    )
    session = RetrySession(job)
    same, created = await retry_existing_analysis(session, settings, job)
    assert same is job and created is False
    assert job.state == "unresolved" and job.retry_count == 0
    assert session.added == []


def test_nested_facts_and_inferences_use_the_same_evidence_allowlist():
    with pytest.raises(ValueError, match="citation"):
        validate_analysis_output(
            {
                "summary": "Summary",
                "evidence_ids": ["run.summary"],
                "facts": [{"statement": "Unsupported fact", "evidence_ids": ["foreign"]}],
                "inferences": [],
                "recommended_actions": [],
            },
            CATALOG,
        )


def analysis_target_snapshot():
    return {
        "target_id": str(uuid.uuid4()),
        "model_version_id": str(uuid.uuid4()),
        "base_url": "https://api.deepseek.com",
        "remote_model": "deepseek-flash",
        "resource_id": str(uuid.uuid4()),
        "container_id": "container",
        "image_id": "image",
        "credential_ref": "secret-reference",
    }


def test_invalid_model_citation_is_archived_as_failed_output():
    native = {
        "state": "succeeded",
        "response": json.dumps(
            {
                "summary": "Unsupported conclusion",
                "evidence_ids": [f"attempt:{uuid.uuid4()}"],
                "facts": [],
                "inferences": [],
                "recommended_actions": ["Approve immediately"],
            }
        ),
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = build_analysis_result(
        native,
        {"evidence_catalog": CATALOG},
        analysis_id=uuid.uuid4(),
        report_id=uuid.uuid4(),
        input_sha256="e" * 64,
        target_snapshot=analysis_target_snapshot(),
    )
    assert result["state"] == "failed"
    assert result["error_code"] == "INVALID_MODEL_OUTPUT"
    assert result["analysis"] is None
    assert result["raw_response"] == native["response"]
    assert "secret-reference" not in json.dumps(result)


def test_valid_model_output_is_immutable_analysis_not_a_gate_decision():
    native = {
        "state": "succeeded",
        "response": json.dumps(
            {
                "summary": "Summary",
                "evidence_ids": ["run.summary"],
                "facts": [],
                "inferences": [],
                "recommended_actions": [],
            }
        ),
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = build_analysis_result(
        native,
        {"evidence_catalog": CATALOG},
        analysis_id=uuid.uuid4(),
        report_id=uuid.uuid4(),
        input_sha256="e" * 64,
        target_snapshot=analysis_target_snapshot(),
    )
    assert result["state"] == "succeeded"
    assert result["analysis"]["evidence_ids"] == ["run.summary"]
    assert result["raw_response"] == native["response"]
    assert set(result) == {
        "schema_version",
        "analysis_id",
        "report_id",
        "input_sha256",
        "state",
        "analysis",
        "raw_response",
        "error_code",
        "finish_reason",
        "usage",
        "model",
    }


def test_analysis_api_and_capabilities_reflect_explicit_configuration():
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.post(f"/api/autoeval/v1/reports/{uuid.uuid4()}/analysis:retry")
        assert response.status_code == 503
        capabilities = client.get("/api/autoeval/v1/system/capabilities").json()["data"]
        assert capabilities["analysis_enabled"] is False

    configured = Settings(
        environment="test",
        analysis_target_id=uuid.uuid4(),
        analysis_resource_id=uuid.uuid4(),
    )
    with TestClient(create_app(configured)) as client:
        capabilities = client.get("/api/autoeval/v1/system/capabilities").json()["data"]
        assert capabilities["analysis_enabled"] is True


def test_report_analysis_status_distinguishes_disabled_unqueued_and_actual_state():
    settings = SimpleNamespace(analysis_target_id=None, analysis_resource_id=None)
    assert analysis_status_for(None, settings) == "not_enabled"
    settings.analysis_target_id = uuid.uuid4()
    settings.analysis_resource_id = uuid.uuid4()
    assert analysis_status_for(None, settings) == "not_queued"
    assert analysis_status_for(SimpleNamespace(state="running"), settings) == "running"
