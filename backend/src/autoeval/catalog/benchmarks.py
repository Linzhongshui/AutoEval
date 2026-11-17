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
    tasks = (snapshot.get("inputs") or {}).get("tasks") or []
    if len(tasks) == 1:
        frozen = compare_frozen_standard(summary, tasks[0])
        if frozen is not None:
            return frozen
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

def compare_frozen_standard(summary, task):
    """Use only the baseline bytes frozen with this task's standard input."""
    source = task.get('standard_baseline_source') or {}
    attachment = source.get('file')
    if not attachment:
        return None
    import hashlib
    import json

    raw = attachment['raw']
    if hashlib.sha256(raw.encode()).hexdigest() != attachment['sha256']:
        raise ValueError('Frozen baseline hash mismatch')
    body = json.loads(raw)
    dataset = task.get('dataset')
    expected = {'GPQA': ('GPQA_Diamond', 'accuracy'),
                'AutomationBench': ('AutomationBench', 'pass_rate')}.get(dataset)
    if not expected or (source.get('benchmark'), body.get('metric')) != expected:
        return _result('incomparable')
    value = body.get('median')
    if body.get('unit') != 'percent' or type(value) not in (int, float) or not 0 <= value <= 100:
        return _result('incomparable')
    result = dict(_result('reference'), baseline_value=value, baseline_unit='percent',
                  baseline_direction='higher_is_better', baseline_version=source['revision'],
                  baseline_key=attachment['path'], source_sha256=attachment['sha256'],
                  source_model=source['source_model'], source_repository=source['repository'],
                  source_notes=body.get('notes'), source_details=body.get('source'),
                  tolerance=body.get('tolerance'), range=body.get('range'), verdict=None)
    measured = summary.get('accuracy')
    if (summary.get('subset_scope') == 'full' and summary.get('scoring_status') == 'succeeded'
            and summary.get('validity') == 'complete' and type(measured) in (int, float)
            and math.isfinite(measured) and 0 <= measured <= 100):
        result.update(status='matched', measured_value=measured, difference=measured-value)
        bounds = body.get('range')
        if (isinstance(bounds, list) and len(bounds) == 2
                and all(type(x) in (int, float) and math.isfinite(x) for x in bounds)
                and bounds[0] <= bounds[1]):
            result['verdict'] = 'within_range' if bounds[0] <= measured <= bounds[1] else 'outside_range'
    return result
