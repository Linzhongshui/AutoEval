import json
from types import SimpleNamespace
from uuid import uuid4

from autoeval.planning import TaskInput
from autoeval.planning_engine import DATASETS
from autoeval.standard_inputs import Bundle, CompileInput, compile_config, discover


def test_automationbench_is_a_supported_selection():
    assert 'AutomationBench' in DATASETS
    assert 'AutomationBench' in TaskInput.model_fields['dataset'].annotation.__args__


def test_automationbench_standard_input_compiles_as_harbor_agent():
    config = {
        "tool": "ais_bench",
        "subcommand": "harbor_agent",
        "params": {
            "agent_import_path": "automationbench_adapter.agent:AutomationBenchOfficialAgent",
            "agent_kwargs": {
                "base_url": "https://api.deepseek.com/v1",
                "sampling_args": {"max_tokens": 65536, "reasoning_effort": "max"},
                "pricing": None,
            },
            "dataset_abbr": "automationbench",
            "n_attempts": 1,
            "max_retries": 0,
            "environment_type": "docker",
        },
    }
    source = Bundle(
        revision="a" * 40,
        files={
            "DeepSeek-V4.1-Flash-1017/AutomationBench/standard_config.json": json.dumps(config)
        },
    )

    entry = discover(source)[0]
    assert entry["mapping"] == {
        "dataset": "AutomationBench",
        "variant": "v1.0.6",
        "subcommand": "harbor_agent",
    }
    result = compile_config(
        entry,
        CompileInput(
            model_id=uuid4(),
            template=config,
            tool_root="/benchmark",
            task_path="/acceptance/tasks",
        ),
        SimpleNamespace(
            id=uuid4(), remote_model="deepseek-flash", base_url="https://api.deepseek.com/v1"
        ),
    )

    assert result["input_ready"]
    assert not result["execution_enabled"]
    assert result["config"]["params"]["model_names"] == ["deepseek-flash"]
    assert result["config"]["params"]["path"] == "/acceptance/tasks"
    assert "api_key" not in result["config"]["params"]
