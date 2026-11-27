import copy
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from autoeval_runtime import native_predictions, planning_runtime


@pytest.mark.parametrize(
    ("dataset", "agent", "import_path", "endpoint", "offline"),
    [
        ("harbor_deepswe-v1.1", "mini-swe-agent", None, "http://10.0.0.1:8000/v1", True),
        ("harbor_deepswe-v1.1", "mini-swe-agent", None, "https://model.example/v1", True),
        ("harbor_deepswe-v1.1", "mini-swe-agent", None, None, False),
        (
            "harbor_deepswe-v1.1",
            "mini-swe-agent",
            "custom:Agent",
            "https://model.example/v1",
            False,
        ),
        ("harbor_deepswe-v1.1", "other", None, "https://model.example/v1", False),
        ("automationbench", "mini-swe-agent", None, "https://model.example/v1", False),
    ],
)
def test_harbor_adaptor_receives_model_and_offline_env(
    tmp_path, monkeypatch, dataset, agent, import_path, endpoint, offline
):
    names = ["deepseek-flash", "openai/custom", "anthropic/claude"]
    params = {
        "dataset_abbr": dataset,
        "agent_name": agent,
        "ais_bench_root": str(tmp_path),
        "model_names": names,
        "agent_env": {"EXISTING": "value"},
        "n_concurrent_trials": 24,
        "llm_kwargs": {"max_tokens": 384000},
    }
    if endpoint:
        params["api_base"] = endpoint
    if import_path:
        params["agent_import_path"] = import_path
    config = {"subcommand": "harbor_agent", "params": params}
    frozen = copy.deepcopy(config)
    (tmp_path / "credential.json").write_text('{"value":"fixture-only"}')
    monkeypatch.setitem(sys.modules, "native_predictions", native_predictions)
    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    monkeypatch.setattr(planning_runtime, "verify_tool", lambda _: None)
    monkeypatch.setattr(
        planning_runtime, "installed_revision", lambda _: planning_runtime.ADAPTOR_REVISION
    )
    monkeypatch.setattr(planning_runtime, "scope_harbor_compose", lambda *_: None)

    def launch(command, *, env, **kwargs):
        assert command[:2] == ["autoeval-adaptor", "--config"]
        actual = json.loads(Path(command[2]).read_text())["params"]
        expected_names = ["openai/deepseek-flash", *names[1:]] if offline else names
        assert actual["model_names"] == expected_names
        assert actual.get("api_base") == endpoint
        assert actual["api_key"] == "fixture-only"
        assert actual["agent_env"]["EXISTING"] == "value"
        assert actual["llm_kwargs"] == params["llm_kwargs"]
        assert actual["n_concurrent_trials"] == 24
        for environment in [env, actual["agent_env"]]:
            assert environment.get("LITELLM_LOCAL_MODEL_COST_MAP") == ("True" if offline else None)
        if endpoint and endpoint.startswith("http:"):
            assert "10.0.0.1" in actual["agent_env"]["NO_PROXY"].split(",")
        (tmp_path / "output" / "unified_result.json").write_text('{"cases":[]}')
        return Mock(returncode=0, poll=lambda: 0)

    monkeypatch.setattr(planning_runtime.subprocess, "Popen", launch)
    result = planning_runtime.execute(
        tmp_path,
        {
            "kind": "adaptor",
            "credential": "runtime-only",
            "tool": {},
            "compilation": {
                "adaptor_revision": planning_runtime.ADAPTOR_REVISION,
                "config": config,
            },
        },
    )
    assert result["tool_exit_code"] == 0
    assert config == frozen
    assert not (tmp_path / "private-config.json").exists()
