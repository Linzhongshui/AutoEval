from autoeval.reporting.result_identity import allowed_result_datasets


def test_cancelled_harbor_native_capture_and_scoring(tmp_path):
    import json

    from autoeval.reporting.result_identity import recover_cancelled_harbor_cases
    from autoeval_runtime.planning_runtime import collect_terminal_harbor_trials

    task = {
        "dataset": "AutomationBench",
        "attempts": 1,
        "samples": [{"tool_case_id": "q1", "sample_id": "case-1"}],
    }

    def write_trial(name, sample, reward):
        trial = tmp_path / name
        (trial / "verifier").mkdir(parents=True)
        (trial / "result.json").write_text(
            json.dumps(
                {
                    "trial_name": name,
                    "task_name": sample,
                    "finished_at": "2026-11-20T01:00:00Z",
                    "verifier_result": {"rewards": {"accuracy": 0}},
                }
            ),
            encoding="utf-8",
        )
        (trial / "verifier/reward.json").write_text(
            json.dumps({"accuracy": reward}), encoding="utf-8"
        )

    write_trial("unknown-trial", "outside-manifest", 0)
    write_trial("q1-trial", "automationbench/q1", 0)
    captured = collect_terminal_harbor_trials(tmp_path, "fixture-credential")
    recovered = recover_cancelled_harbor_cases(task, captured)
    assert [(case["case_id"], case["score"]) for case in recovered["cases"]] == [("case-1", 0)]
    assert recover_cancelled_harbor_cases({**task, "attempts": 2}, captured) is None
    assert recover_cancelled_harbor_cases(task, [*captured, *captured]) is None
    (tmp_path / "q1-trial/verifier/reward.json").write_text('{"accuracy":1}', encoding="utf-8")
    assert (
        recover_cancelled_harbor_cases(
            task, collect_terminal_harbor_trials(tmp_path, "fixture-credential")
        )
        is None
    )


def test_cancelled_deepswe_restores_only_complete_journalled_group():
    import json

    from autoeval.reporting.result_identity import recover_cancelled_harbor_cases

    task = {
        "dataset": "DeepSWE",
        "attempts": 2,
        "samples": [{"tool_case_id": "q1", "sample_id": "case-1"}],
    }
    trials = [
        {
            "trial_name": name,
            "files": {
                "result.json": json.dumps(
                    {
                        "trial_name": name,
                        "task_name": "datacurve/q1",
                        "finished_at": "2026-11-20T01:00:00Z",
                        "verifier_result": {"rewards": {"reward": score}},
                    }
                )
            },
        }
        for name, score in [("z-trial", 0), ("a-trial", 1)]
    ]
    dispatch = {
        "trials": [{"tool_case_id": "q1", "trial_name": trial["trial_name"]} for trial in trials]
    }
    result = recover_cancelled_harbor_cases(task, trials, dispatch)
    assert [(case["attempt"], case["score"]) for case in result["cases"]] == [(1, 1), (2, 0)]
    assert recover_cancelled_harbor_cases(task, trials[:1], dispatch) is None
    assert recover_cancelled_harbor_cases(task, trials, {"trials": []}) is None


def test_automationbench_native_accuracy_requires_matching_evidence():
    import json

    import pytest

    from autoeval.reporting.result_identity import apply_automationbench_accuracy

    case = {
        "harbor_artifact": {
            "files": {
                "verifier/reward.json": json.dumps({"accuracy": 1.0}),
                "result.json": json.dumps({"verifier_result": {"rewards": {"accuracy": 1.0}}}),
            }
        }
    }
    apply_automationbench_accuracy(case)
    assert case["score"] == 1.0 and case["score_name"] == "accuracy"
    case.pop("score")
    case["harbor_artifact"]["files"]["verifier/reward.json"] = '{"accuracy": 0.0}'
    with pytest.raises(ValueError, match="conflicts"):
        apply_automationbench_accuracy(case)
    missing = {"harbor_artifact": {"files": {}}}
    apply_automationbench_accuracy(missing)
    assert "score" not in missing


def test_automation_registry_name_matches_adaptor():
    names = allowed_result_datasets(
        "AutomationBench",
        {
            "subcommand": "harbor_agent",
            "params": {"dataset_name_version": "org/AutomationBench@1.0.6"},
        },
    )
    assert names == {"AutomationBench", "harbor_AutomationBench"}
    assert "unrelated" not in names


def test_explicit_abbr_and_local_directory():
    assert "harbor_cases" in allowed_result_datasets(
        "AutomationBench", {"subcommand": "harbor_agent", "params": {"path": "/tasks/cases/"}}
    )
    names = allowed_result_datasets(
        "AutomationBench",
        {
            "subcommand": "harbor_agent",
            "params": {"path": "/tasks/cases/", "dataset_abbr": "automation-fixed"},
        },
    )
    assert names == {"AutomationBench", "automation-fixed"}


def test_accuracy_aliases_still_supported():
    assert allowed_result_datasets("GPQA", {"subcommand": "llm_accuracy", "params": {}}) == {
        "GPQA",
        "GPQA_diamond",
    }


def test_automationbench_directory_and_native_name_are_distinct():
    from autoeval.reporting.result_identity import result_case_aliases

    samples = [
        {
            "tool_case_id": "automationbench-support-1587-0252fa3e9d",
            "sample_id": "automationbench-support-1587-0252fa3e9d",
        }
    ]
    aliases = result_case_aliases("AutomationBench", samples)
    native = "automationbench/automationbench-support-1587-0252fa3e9d"
    assert aliases[native] == samples[0]["sample_id"]
    assert aliases[samples[0]["tool_case_id"]] == samples[0]["sample_id"]
    assert "other/automationbench-support-1587-0252fa3e9d" not in aliases
    assert "automationbench/unknown" not in aliases
    assert native not in result_case_aliases("DeepSWE", samples)


def test_harbor_omitted_dataset_uses_frozen_identity_without_mutation():
    import pytest

    from autoeval.reporting.result_identity import normalize_result_identities

    raw = {"cases": [{"case_id": "automationbench/task-one", "attempt": 1}]}
    config = {"subcommand": "harbor_agent", "params": {}}
    samples = [{"sample_id": "task-one", "tool_case_id": "task-one"}]
    result = normalize_result_identities(raw, "AutomationBench", config, samples)
    assert result["cases"][0] == {"case_id": "task-one", "attempt": 1, "dataset": "AutomationBench"}
    assert (
        raw["cases"][0]["case_id"] == "automationbench/task-one"
        and "dataset" not in raw["cases"][0]
    )
    with pytest.raises(ValueError):
        normalize_result_identities(
            {"cases": [{"dataset": "foreign", "case_id": "task-one"}]},
            "AutomationBench",
            config,
            samples,
        )
    with pytest.raises(ValueError):
        normalize_result_identities(
            {"cases": [{"case_id": "other/task-one"}]}, "AutomationBench", config, samples
        )
