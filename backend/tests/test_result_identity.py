from autoeval.result_identity import allowed_result_datasets


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
