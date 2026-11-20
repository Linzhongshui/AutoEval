import math

import pytest
from fastapi.testclient import TestClient

from autoeval.entrypoints.api import create_app
from autoeval.infrastructure.config import Settings
from autoeval.reporting.leaderboards import rank_leaderboard


def report(report_id, accuracy, *, validity="complete", manifest="manifest-a", model="model-a"):
    return {
        "report_id": report_id,
        "run_id": f"run-{report_id}",
        "remote_model": model,
        "created_at": "2026-11-10T00:00:00+00:00",
        "validity": validity,
        "summary": {"accuracy": accuracy},
        "snapshot": {
            "manifest_id": manifest,
            "manifest_sha256": f"sha-{manifest}",
            "tool": {"revision": "tool-a"},
            "parameters": {
                "output": 32,
                "concurrency": 1,
                "temperature": 0,
                "top_p": 1,
                "scope": "Lite",
            },
        },
    }


def test_leaderboard_preserves_all_reports_and_separates_comparison_groups():
    groups = rank_leaderboard(
        [
            report("low", 50),
            report("high", 75),
            report("partial", 100, validity="partial"),
            report("other-manifest", 90, manifest="manifest-b"),
        ],
        dataset_key="GPQA",
        metric_name="accuracy",
    )

    assert len(groups) == 2
    first = next(group for group in groups if group["comparison"]["manifest_id"] == "manifest-a")
    assert [entry["report_id"] for entry in first["entries"]] == ["high", "low"]
    assert [entry["rank"] for entry in first["entries"]] == [1, 2]
    assert first["direction"] == "higher_is_better"
    assert first["unit"] == "%"


def test_leaderboard_rejects_invalid_measured_values_instead_of_ranking_them():
    with pytest.raises(ValueError, match="Invalid leaderboard metric"):
        rank_leaderboard([report("nan", math.nan)], dataset_key="GPQA", metric_name="accuracy")


def test_leaderboard_api_validates_dataset_before_database():
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get(
            "/api/autoeval/v1/leaderboard",
            params={"dataset_key": "unknown", "metric_name": "accuracy"},
        )
        assert response.status_code == 422


def test_unknown_execution_conditions_do_not_form_a_comparable_group():
    rows = [report("a", 60), report("b", 70)]
    for row in rows:
        row["snapshot"]["parameters"]["temperature"] = None
    groups = rank_leaderboard(rows, dataset_key="GPQA", metric_name="accuracy")
    assert len(groups) == 2
    assert all("unconfirmed_conditions_report_id" in g["comparison"] for g in groups)
