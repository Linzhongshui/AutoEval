"""Pure T1 badcase scoring tests; no database or object storage is used."""

from autoeval.reporting.badcases import (
    canonical_dataset,
    config_view,
    history_stats,
    same_config,
    soft_signals,
    sort_cases,
    verdict,
)


def context(*, dataset="GPQA", samples=None, output=2048, target="target-1"):
    samples = samples or [{"sample_id": "gpqa_diamond:0", "sha256": "a" * 64}]
    task = {
        "task_id": dataset,
        "dataset": dataset,
        "manifest_sha256": "b" * 64,
        "subset_scope": "lite",
        "concurrency": 1,
        "samples": samples,
        "tool": {"revision": "tool-rev"},
        "compilation": {
            "config": {
                "subcommand": "llm_accuracy",
                "params": {
                    "max_out_len": output,
                    "generation_kwargs": {"temperature": 0.0, "top_p": 1.0},
                },
            }
        },
    }
    return {
        "schema_version": "planned-run.v1",
        "dataset_key": dataset,
        "remote_model": "deepseek-flash",
        "target_id": target,
        "manifest_sha256": "b" * 64,
        "execution_origin": "real",
        "inputs": {"tasks": [task]},
    }


def current_case(**overrides):
    value = {
        "score": 0.0,
        "state": "succeeded",
        "attempt_no": 1,
        "error_code": None,
        "has_evidence": True,
        "trace_status": "succeeded",
        "input_tokens": 10,
        "output_tokens": 20,
        "duration_sec": None,
    }
    value.update(overrides)
    return value


def test_canonical_dataset_unifies_gpqa_spellings():
    assert canonical_dataset(context()) == "GPQA-Diamond"
    old = context(dataset="GPQA_diamond", samples=[{"sample_id": "0", "sha256": "a" * 64}])
    assert canonical_dataset(old) == "GPQA-Diamond"
    assert canonical_dataset(context(dataset="AutomationBench")) == "AutomationBench"


def test_config_view_reads_planned_task_and_legacy_snapshot():
    task_config = config_view(context())
    assert task_config["output"] == 2048
    assert task_config["scope"] == "lite"
    assert task_config["manifest_sha256"] == "b" * 64
    legacy = {
        "remote_model": "deepseek-flash",
        "target_id": "target-1",
        "manifest_sha256": "b" * 64,
        "tool": {"revision": "tool-rev"},
        "parameters": {"output": 2048, "concurrency": 1, "temperature": 0.0,
                       "top_p": 1.0, "scope": "Lite"},
    }
    assert config_view(legacy) == task_config


def test_same_config_requires_target_and_all_conditions():
    left = config_view(context())
    assert same_config(left, config_view(context()))
    assert not same_config(left, config_view(context(output=4096)))
    assert not same_config(left, config_view(context(target="target-2")))
    missing = dict(left)
    missing.pop("target_id")
    assert same_config(left, missing)


def test_history_stats_excludes_missing_scores():
    stats = history_stats(
        [
            {"report_id": "1", "run_id": "r1", "created_at": "now", "score": 1.0},
            {"report_id": "2", "run_id": "r2", "created_at": "now", "score": 0.0},
            {"report_id": "3", "run_id": "r3", "created_at": "now", "score": None},
        ]
    )
    assert stats["n"] == 2
    assert stats["k"] == 1
    assert stats["mean"] == 0.5


def test_hard_signal_is_high_even_with_history():
    result = verdict(
        current_case(state="failed", error_code="UPSTREAM_TIMEOUT"),
        history_stats([]),
        soft_signals(current_case(state="failed", error_code="UPSTREAM_TIMEOUT"), "llm_accuracy"),
        "llm_accuracy",
    )
    assert result["is_badcase"] is True
    assert result["band"] == "high"
    assert result["method"] == "hard"
    assert result["p_hat"] == 0.0


def test_t1_low_band_and_expected_failure():
    stats = history_stats(
        [
            {"report_id": "1", "run_id": "r1", "created_at": "now", "score": 1.0},
            {"report_id": "2", "run_id": "r2", "created_at": "now", "score": 1.0},
            {"report_id": "3", "run_id": "r3", "created_at": "now", "score": 1.0},
            {"report_id": "4", "run_id": "r4", "created_at": "now", "score": 0.0},
        ]
    )
    suspicious = verdict(current_case(), stats, [], "llm_accuracy")
    assert suspicious["is_badcase"] is True
    assert suspicious["band"] == "low"
    assert suspicious["p_hat"] == 0.6667
    assert suspicious["suspicion"] == 0.3333

    expected = verdict(
        current_case(),
        history_stats(
            [{"report_id": str(i), "run_id": f"r{i}", "created_at": "now", "score": 0.0}
             for i in range(4)]
        ),
        [],
        "llm_accuracy",
    )
    assert expected["is_badcase"] is False
    assert expected["band"] == "non_badcase"
    assert expected["suspicion"] == 0.0
    assert expected["why_not_badcase"].startswith("low-expected-pass-rate")


def test_no_history_falls_back_to_low_confidence_failure():
    result = verdict(current_case(), history_stats([]), [], "llm_accuracy")
    assert result["is_badcase"] is True
    assert result["band"] == "low"
    assert result["method"] == "fallback"
    assert result["p_hat"] is None
    assert result["suspicion"] == 0.5


def test_pass_is_non_badcase_and_suspicious_pass_is_low():
    passed = verdict(current_case(score=1.0), history_stats([]), [], "llm_accuracy")
    assert passed["band"] == "non_badcase"
    assert passed["method"] == "pass"
    suspicious = verdict(
        current_case(score=1.0, has_evidence=False),
        history_stats([]),
        soft_signals(current_case(score=1.0, has_evidence=False), "llm_accuracy"),
        "llm_accuracy",
    )
    assert suspicious["band"] == "low"
    assert suspicious["method"] == "suspicious_pass"


def test_harbor_missing_trace_and_duration_are_soft_signals():
    signals = soft_signals(
        current_case(trace_status="missing", duration_sec=None), "harbor_agent"
    )
    assert "no-trace" in signals
    assert "no-duration" in signals
    assert "no-trace" not in soft_signals(current_case(duration_sec=None), "llm_accuracy")


def test_cases_sort_by_band_then_suspicion():
    rows = [
        {"sample_id": "non", "verdict": {"band": "non_badcase", "suspicion": 0.0}},
        {"sample_id": "low", "verdict": {"band": "low", "suspicion": 0.3}},
        {"sample_id": "high", "verdict": {"band": "high", "suspicion": 1.0}},
    ]
    assert [row["sample_id"] for row in sort_cases(rows)] == ["high", "low", "non"]
