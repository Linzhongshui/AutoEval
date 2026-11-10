from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from autoeval.reports import report_data


def snapshot():
    return SimpleNamespace(
        canonical_body={
            "remote_model": "model-a",
            "config_version_id": str(uuid4()),
            "manifest_id": str(uuid4()),
            "manifest_sha256": "a" * 64,
            "tool": {"revision": "tool-a"},
            "parameters": {"output": 32, "concurrency": 1, "temperature": 0, "top_p": 1, "scope": "Lite"},
        }
    )


def report():
    return SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        validity="complete",
        summary={"accuracy": 60, "subset_scope": "lite"},
        sha256="b" * 64,
        snapshot_sha256="c" * 64,
        execution_origin="real",
    )


def baseline(snapshot_body):
    return SimpleNamespace(
        baseline_key="approved-fixture",
        version="v1",
        dataset_key="GPQA",
        subset_scope="lite",
        metric_name="accuracy",
        unit="percent",
        value=50,
        direction="higher_is_better",
        conditions={
            "dataset_key": "GPQA",
            "manifest_sha256": snapshot_body["manifest_sha256"],
            "tool_revision": "tool-a",
            **snapshot_body["parameters"],
            "scope": "lite",
        },
    )


def test_report_data_includes_only_condition_exact_baseline_difference():
    frozen = snapshot()
    run = SimpleNamespace(run_mode="exploration")
    matched = report_data(report(), run, frozen, [baseline(frozen.canonical_body)])
    assert matched["baseline_comparison"]["status"] == "matched"
    assert matched["baseline_comparison"]["difference"] == 10

    missing = report_data(report(), run, frozen, [])
    assert missing["baseline_comparison"]["status"] == "missing"
    assert missing["baseline_comparison"]["difference"] is None
