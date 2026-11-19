from autoeval.reporting.result_identity import allowed_result_datasets


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
