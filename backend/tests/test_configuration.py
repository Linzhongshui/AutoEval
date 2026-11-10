import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from autoeval.api import create_app
from autoeval.config import Settings
from autoeval.configuration import Parameters


def test_configuration_rejects_unknown_and_unbounded_parameters():
    with pytest.raises(ValidationError):
        Parameters(output=100, concurrency=0, temperature=0.5, top_p=1, scope="全量")
    with pytest.raises(ValidationError):
        Parameters(output=100, concurrency=1, temperature=float("nan"), top_p=1, scope="全量")


def test_config_api_is_registered_and_validates_before_database():
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.post("/api/autoeval/v1/test-configs", json={})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert client.get("/api/autoeval/v1/test-configs?limit=201").status_code == 422
