import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from autoeval.api import create_app
from autoeval.config import Settings
from autoeval.domain import RunState, check_transition
from autoeval.models import Base


def test_live_and_honest_capabilities():
    with TestClient(create_app(Settings(environment="test"))) as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        response = client.get("/api/autoeval/v1/system/capabilities")
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == response.json()["request_id"]
        assert response.json()["data"]["evaluation_enabled"] is False
        assert client.post("/api/autoeval/v1/runs", json={}).status_code == 422
        assert (
            client.post("/api/autoeval/v1/runs", json={}).json()["error"]["code"]
            == "VALIDATION_ERROR"
        )


def test_terminal_state_cannot_regress():
    check_transition(RunState.RUNNING, RunState.CANCELLING)
    with pytest.raises(ValueError):
        check_transition(RunState.COMPLETED, RunState.RUNNING)


def test_local_identity_cannot_be_used_in_production():
    with pytest.raises(ValueError):
        Settings(environment="production")


def test_schema_is_single_workspace_and_postgres_compilable():
    for table in Base.metadata.sorted_tables:
        assert "project_id" not in table.c
        sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in sql


async def test_workflows_validate_in_temporal_sandbox():
    from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner
    from temporalio.workflow import _Definition

    from autoeval.workflows import AnalysisWorkflow, RunWorkflow

    for cls in (RunWorkflow, AnalysisWorkflow):
        SandboxedWorkflowRunner().prepare_workflow(_Definition.must_from_class(cls))


async def test_unconfigured_activities_cannot_fake_success():
    from temporalio.exceptions import ApplicationError

    from autoeval.activities import analysis_not_configured, execution_not_configured

    for activity in (execution_not_configured, analysis_not_configured):
        with pytest.raises(ApplicationError) as exc:
            await activity("example")
        assert exc.value.non_retryable


def test_readiness_does_not_claim_success_when_dependencies_fail(monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("autoeval.api.Client.connect", AsyncMock(side_effect=OSError("offline")))

    def unavailable(*args, **kwargs):
        raise OSError("storage offline")

    monkeypatch.setattr("autoeval.api.boto3.client", unavailable)
    settings = Settings(
        environment="test",
        dependency_timeout_seconds=0.1,
        database_url="postgresql+asyncpg://user:password@127.0.0.1:1/unavailable",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert set(response.json()["checks"].values()) == {"unavailable"}
        assert "password" not in response.text
