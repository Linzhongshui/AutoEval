"""Internal leaderboard over complete, comparable real reports."""

import asyncio
import math
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.datasets import canonical_manifest
from autoeval.evaluations import EvaluationReport
from autoeval.models import EvaluationRun, RunSnapshot
from autoeval.report_integrity import report_evidence_status

router = APIRouter(prefix="/api/autoeval/v1/leaderboard", tags=["internal leaderboard"])


def rank_leaderboard(rows, *, dataset_key: str, metric_name: str):
    if metric_name != "accuracy":
        raise ValueError("Unsupported leaderboard metric")
    groups = {}
    for row in rows:
        if row["validity"] != "complete":
            continue
        value = row["summary"].get(metric_name)
        if value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("Invalid leaderboard metric")
        snapshot = row["snapshot"]
        comparison = {
            "dataset_key": dataset_key,
            "manifest_id": snapshot["manifest_id"],
            "manifest_sha256": snapshot["manifest_sha256"],
            "tool_revision": snapshot["tool"]["revision"],
            "parameters": {
                key: snapshot["parameters"][key]
                for key in ("output", "concurrency", "temperature", "top_p", "scope")
            },
        }
        identity = canonical_manifest(comparison)
        group = groups.setdefault(
            identity,
            {
                "comparison": comparison,
                "metric_name": metric_name,
                "unit": "%",
                "direction": "higher_is_better",
                "entries": [],
            },
        )
        group["entries"].append(
            {
                "report_id": row["report_id"],
                "run_id": row["run_id"],
                "remote_model": row["remote_model"],
                "created_at": row["created_at"],
                "value": value,
            }
        )
    for group in groups.values():
        group["entries"].sort(
            key=lambda entry: (-entry["value"], entry["created_at"], entry["report_id"]),
            reverse=False,
        )
        previous_value, previous_rank = None, None
        for index, entry in enumerate(group["entries"], start=1):
            if entry["value"] != previous_value:
                previous_rank = index
                previous_value = entry["value"]
            entry["rank"] = previous_rank
    return [groups[key] for key in sorted(groups)]


@router.get("")
async def leaderboard(
    request: Request,
    dataset_key: Literal["GPQA", "MMMU-Pro", "AutomationBench"],
    metric_name: Literal["accuracy"],
):
    # The implemented report schema is GPQA-only. Never relabel GPQA rows as a
    # different benchmark merely because the query contains another dataset.
    if dataset_key != "GPQA":
        return {
            "data": [],
            "excluded_unverified_reports": 0,
            "request_id": request.state.request_id,
        }
    try:
        async with request.app.state.sessions() as session:
            rows = (
                await session.execute(
                    select(EvaluationReport, EvaluationRun, RunSnapshot)
                    .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
                    .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
                    .where(
                        EvaluationRun.trigger_scope == "local-operator:evaluation",
                        EvaluationReport.execution_origin == "real",
                        EvaluationReport.validity == "complete",
                        RunSnapshot.schema_version == "gpqa-run.v1",
                    )
                    .order_by(EvaluationReport.created_at.desc(), EvaluationReport.id.desc())
                )
            ).all()
            semaphore = asyncio.Semaphore(8)

            async def check(row):
                async with semaphore:
                    return await report_evidence_status(request.app.state.settings, *row)

            statuses = await asyncio.gather(*(check(row) for row in rows))
            verified = [
                row for row, status in zip(rows, statuses, strict=True) if status == "verified"
            ]
            data = rank_leaderboard(
                [
                    {
                        "report_id": str(report.id),
                        "run_id": str(run.id),
                        "remote_model": snapshot.canonical_body["remote_model"],
                        "created_at": report.created_at.isoformat(),
                        "validity": report.validity,
                        "summary": report.summary,
                        "snapshot": snapshot.canonical_body,
                    }
                    for report, run, snapshot in verified
                ],
                dataset_key=dataset_key,
                metric_name=metric_name,
            )
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Leaderboard database unavailable") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, "Leaderboard source data is invalid") from exc
    return {
        "data": data,
        "excluded_unverified_reports": len(rows) - len(verified),
        "request_id": request.state.request_id,
    }
