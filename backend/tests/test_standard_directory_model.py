from datetime import datetime, UTC
from types import SimpleNamespace
from uuid import uuid4

from autoeval import standard_inputs


def test_directory_model_overrides_service_alias_without_mutating_snapshot(monkeypatch):
    monkeypatch.setattr(standard_inputs, "input_readiness", lambda payload: {})
    payload = {
        "source_model": "deepseek-flash",
        "files": {
            "standard_config.json": {
                "path": "DeepSeek-V4.1-Flash-1017/AutomationBench/standard_config.json"
            }
        },
    }
    row = SimpleNamespace(
        id=uuid4(),
        repository="repo",
        revision="a" * 40,
        source_model="deepseek-flash",
        benchmark="AutomationBench",
        content_sha256="hash",
        created_at=datetime.now(UTC),
        payload=payload,
    )
    assert standard_inputs.row_data(row)["source_model"] == "DeepSeek-V4.1-Flash-1017"
    assert payload["source_model"] == "deepseek-flash"
