"""Present archived report metadata using the existing API fields."""

from autoeval.catalog.benchmarks import compare_baseline
from autoeval.catalog.dataset_identity import report_dataset


def report_data(
    row,
    run,
    snapshot,
    baselines=(),
    *,
    analysis_status="not_enabled",
    analysis_id=None,
    evidence_status="not_checked",
):

    aggregate = "parameters" not in snapshot.canonical_body

    comparison = (
        {"status": "incomparable", "baseline_value": None, "difference": None}
        if aggregate
        else compare_baseline(row.summary, snapshot.canonical_body, baselines)
    )

    if evidence_status != "verified":
        comparison = {
            **comparison,
            "status": "incomparable",
            "measured_value": None,
            "difference": None,
            "reason": "report_evidence_unverified",
        }

    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "dataset_concurrency": (snapshot.canonical_body.get("inputs") or {}).get("dataset_concurrency", 1),
        "execution_kind": "planned"
        if snapshot.canonical_body.get("schema_version") == "planned-run.v1"
        else "evaluation",
        "created_at": row.created_at.isoformat(),
        "validity": row.validity,
        "evidence_status": evidence_status,
        "summary": row.summary,
        "dataset_key": "多个数据集" if aggregate else report_dataset(snapshot.canonical_body),
        "sha256": row.sha256,
        "snapshot_sha256": row.snapshot_sha256,
        "run_mode": run.run_mode,
        "remote_model": snapshot.canonical_body["remote_model"],
        "config_version_id": snapshot.canonical_body.get("config_version_id"),
        "manifest_id": snapshot.canonical_body.get("manifest_id"),
        "nomination_conditions": {
            **snapshot.canonical_body.get("parameters", {}),
            "manifest_sha256": snapshot.canonical_body.get("manifest_sha256"),
            "tool_revision": snapshot.canonical_body.get("tool", {}).get("revision"),
        },
        "execution_origin": row.execution_origin,
        "gate_status": "not_applicable",
        "analysis_status": analysis_status,
        "analysis_id": str(analysis_id) if analysis_id else None,
        "baseline_comparison": comparison,
        "review_status": getattr(row, "review_status", "pending"),
        "reviewed_by": getattr(row, "reviewed_by", None),
        "reviewed_at": (
            row.reviewed_at.isoformat()
            if getattr(row, "reviewed_at", None)
            else None
        ),
        "review_note": getattr(row, "review_note", None),
    }
