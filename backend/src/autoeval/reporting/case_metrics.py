"""Verified read projection for current case metrics; original attempts remain immutable."""

import asyncio
import copy
import hashlib
from types import SimpleNamespace

from sqlalchemy import select

from autoeval.catalog.datasets import canonical_manifest, read_manifest
from autoeval.evaluation.models import EvaluationReport
from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
from autoeval.reporting.report_integrity import report_evidence_status
from autoeval.reporting.unified_outputs import parse_output


def metric_view(original, recovered=None):
    value = copy.deepcopy(original or {})
    if recovered is not None:
        value.update({k: v for k, v in recovered.items() if k != "raw"})
    if value.get("duration_sec") is None:
        value["duration_status"] = "not_collected"
    if value.get("input_tokens") is None or value.get("output_tokens") is None:
        value["token_status"] = "not_collected"
    return value


async def current_metrics(session, settings, run_id, rows):
    """Select only archives explicitly referenced by the task's formal report."""
    result = {r.id: (metric_view(r.tool_metadata), None) for r in rows}
    report = await session.scalar(select(EvaluationReport).where(EvaluationReport.run_id == run_id))
    if report is None:
        return result
    body = await asyncio.to_thread(read_manifest, settings, report)
    if body.get("schema_version") != "task-report.v2":
        return result
    snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
    run = await session.get(EvaluationRun, run_id)
    if (
        run is None
        or snapshot is None
        or await report_evidence_status(settings, report, run, snapshot) != "verified"
    ):
        raise ValueError("Current case metrics require verified task report evidence")
    for section in body["datasets"]:
        ref = section.get("archive")
        wanted = [r for r in rows if r.dataset_key == section["dataset_key"]]
        if not wanted or not ref or ref.get("kind") != "recovery":
            continue
        raw = await asyncio.to_thread(read_manifest, settings, SimpleNamespace(**ref))
        cases, _ = parse_output(
            canonical_manifest(raw),
            {section["dataset_key"]: [s["sample_id"] for s in section["context"]["samples"]]},
            section["dataset_key"],
        )
        by_identity = {(c["sample_id"], c["attempt_no"]): c for c in cases}
        for row in wanted:
            recovered = by_identity.get((row.sample_id, row.attempt_no))
            if recovered is None:
                raise ValueError("Recovered metrics have no matching original attempt")
            provenance = {
                "kind": "verified_report_recovery",
                "report_id": str(report.id),
                "report_sha256": report.sha256,
                "archive_id": ref["id"],
                "archive_sha256": ref["sha256"],
                "original_evidence_sha256": row.sha256,
                "case_sha256": hashlib.sha256(canonical_manifest(recovered)).hexdigest(),
            }
            result[row.id] = (metric_view(row.tool_metadata, recovered), provenance)
    return result
