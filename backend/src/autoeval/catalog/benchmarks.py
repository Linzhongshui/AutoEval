"""Immutable benchmark records and condition-exact GPQA accuracy comparison."""

import math

REQUIRED_CONDITIONS = frozenset(
    {
        "dataset_key",
        "manifest_sha256",
        "tool_revision",
        "output",
        "concurrency",
        "temperature",
        "top_p",
        "scope",
    }
)
_MISSING = object()


def _result(status, baseline=None):
    return {
        "status": status,
        "baseline_key": baseline.baseline_key if baseline else None,
        "baseline_version": baseline.version if baseline else None,
        "baseline_value": baseline.value if baseline else None,
        "baseline_unit": baseline.unit if baseline else None,
        "baseline_direction": baseline.direction if baseline else None,
        "measured_value": None,
        "difference": None,
    }


def _snapshot_value(snapshot, key):
    value = snapshot
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _equal(left, right):
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _conditions_match(baseline, snapshot, signature):
    conditions = baseline.conditions
    if any(
        key not in conditions or not _equal(conditions[key], value)
        for key, value in signature.items()
    ):
        return False
    return all(
        key in signature
        or (
            _snapshot_value(snapshot, key) is not _MISSING
            and _equal(_snapshot_value(snapshot, key), value)
        )
        for key, value in conditions.items()
    )


def compare_baseline(summary, snapshot, baselines):
    """Compare only GPQA Lite accuracy in percent; never synthesize a zero baseline."""
    parameters = snapshot["parameters"]
    signature = {
        "dataset_key": snapshot.get("dataset_key", "GPQA"),
        "manifest_sha256": snapshot["manifest_sha256"],
        "tool_revision": snapshot["tool"]["revision"],
        "output": parameters["output"],
        "concurrency": parameters["concurrency"],
        "temperature": parameters["temperature"],
        "top_p": parameters["top_p"],
        "scope": parameters["scope"].lower(),
    }
    candidates = [row for row in baselines if row.metric_name == "accuracy"]
    matched = next(
        (
            row
            for row in candidates
            if row.dataset_key == signature["dataset_key"]
            and row.subset_scope == "lite"
            and summary.get("subset_scope") == "lite"
            and signature["scope"] == "lite"
            and row.unit == "percent"
            and _conditions_match(row, snapshot, signature)
        ),
        None,
    )
    if matched is None:
        return _result("incomparable" if candidates else "missing")

    result = _result("matched", matched)
    measured = summary.get("accuracy")
    if type(measured) in (int, float) and math.isfinite(measured):
        result["measured_value"] = measured
        result["difference"] = measured - matched.value
    return result
