import pytest

from autoeval.evaluation.resume_selection import remaining_payloads


@pytest.mark.parametrize("dataset", ["DeepSWE", "AutomationBench"])
def test_harbor_single_case_preserves_frozen_attempts(dataset):
    params = {"n_attempts": 3, "task_names": ["native-a", "native-b"], "n_tasks": 2}
    frozen = {
        "dataset": dataset,
        "attempts": 3,
        "concurrency": 2,
        "samples": [
            {"sample_id": "a", "tool_case_id": "native-a"},
            {"sample_id": "b", "tool_case_id": "native-b"},
        ],
        "compilation": {"config": {"subcommand": "harbor_agent", "params": params}},
    }

    (shard,) = remaining_payloads(frozen, {"b"})

    assert shard["samples"] == frozen["samples"][1:]
    assert shard["compilation"]["config"]["params"] == {
        "n_attempts": 3,
        "task_names": ["native-b"],
    }
    assert shard["attempts"] == 3
    assert shard["concurrency"] == 2
    assert params["task_names"] == ["native-a", "native-b"]
