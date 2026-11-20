import json
from types import SimpleNamespace

from autoeval_runtime.planning_runtime import check_tool_environment


def test_preflight_only_uses_placeholder_and_preserves_config(monkeypatch):
    config = {
        "tool": "ais_bench",
        "subcommand": "harbor_agent",
        "params": {"work_dir": "/original"},
    }

    def run(command, **kwargs):
        assert command[-1] == "--preflight-only"
        body = json.loads(
            __import__("pathlib").Path(command[command.index("--config") + 1]).read_text()
        )
        assert body["params"]["api_key"] == "non-generating-preflight-placeholder"
        assert kwargs["capture_output"] is True
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr("autoeval_runtime.planning_runtime.subprocess.run", run)
    assert not check_tool_environment(config)
    assert config["params"] == {"work_dir": "/original"}


def test_automationbench_uses_harbor_resource_reservations():
    from autoeval.evaluation.service import demand_for

    task = {
        "dataset": "AutomationBench",
        "concurrency": 1,
        "compilation": {"config": {"params": {}}},
    }
    demand = demand_for(task)
    assert demand["networks"] == 1 and demand["mem"] >= 8192
    assert demand == demand_for({**task, "dataset": "DeepSWE"})


def test_task_selection_preflight_never_runs_agent(monkeypatch):
    from autoeval_runtime.planning_runtime import check_task_selection

    def run(command, **kwargs):
        assert "get_task_configs" in command[2] and "Job(" not in command[2]
        assert json.loads(command[3])["task_names"] == ["directory-id"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("autoeval_runtime.planning_runtime.subprocess.run", run)
    assert check_task_selection(
        {
            "params": {
                "path": "/tasks",
                "task_names": ["directory-id"],
                "python_executable": "/python",
            }
        }
    )
