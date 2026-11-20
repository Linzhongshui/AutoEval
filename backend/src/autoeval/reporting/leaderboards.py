"""Internal leaderboard over complete, comparable real reports."""

import asyncio
import math
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.catalog.dataset_identity import report_dataset
from autoeval.catalog.datasets import canonical_manifest
from autoeval.evaluation.models import EvaluationReport
from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
from autoeval.infrastructure.responses import LeaderboardEnvelope
from autoeval.reporting.report_integrity import verified_report_body

router = APIRouter(prefix="/api/autoeval/v1/leaderboard", tags=["internal leaderboard"])


class LeaderboardEntry(BaseModel):
    report_id: str
    run_id: str
    remote_model: str
    created_at: str
    value: int | float
    rank: int


class LeaderboardGroup(BaseModel):
    comparison: dict
    metric_name: str
    unit: str
    direction: str
    entries: list[LeaderboardEntry]


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
            "dataset_key": report_dataset(snapshot),
            "manifest_id": snapshot["manifest_id"],
            "manifest_sha256": snapshot["manifest_sha256"],
            "tool_revision": snapshot["tool"]["revision"],
            "parameters": {
                key: snapshot["parameters"][key]
                for key in ("output", "concurrency", "temperature", "top_p", "scope")
            },
        }
        if any(value is None for value in comparison["parameters"].values()):
            comparison["unconfirmed_conditions_report_id"] = row["report_id"]
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


@router.get("", response_model=LeaderboardEnvelope[LeaderboardGroup])
async def leaderboard(
    request: Request,
    dataset_key: Literal["GPQA", "GPQA-Diamond", "MMMU-Pro", "AutomationBench"],
    metric_name: Literal["accuracy"],
):
    try:
        async with request.app.state.sessions() as session:
            rows = (
                await session.execute(
                    select(EvaluationReport, EvaluationRun, RunSnapshot)
                    .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
                    .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
                    .where(
                        EvaluationRun.trigger_scope.in_(
                            ["local-operator:evaluation", "local-operator:orchestration"]
                        ),
                        EvaluationReport.is_current,
                        EvaluationReport.execution_origin == "real",
                        EvaluationReport.validity.in_(["complete", "partial"]),
                    )
                    .order_by(EvaluationReport.created_at.desc(), EvaluationReport.id.desc())
                )
            ).all()
            semaphore = asyncio.Semaphore(8)

            async def check(row):
                async with semaphore:
                    return await verified_report_body(request.app.state.settings, *row)

            evidence = await asyncio.gather(*(check(row) for row in rows))
            entries = []
            excluded = 0
            for (report, run, snapshot), (status, body) in zip(rows, evidence, strict=True):
                if status != "verified" or body is None:
                    excluded += 1
                    continue
                sections = (
                    body.get("datasets", [])
                    if body.get("schema_version") == "task-report.v2"
                    else [
                        {
                            "context": snapshot.canonical_body,
                            "summary": report.summary,
                            "validity": report.validity,
                        }
                    ]
                )
                for d in sections:
                    context = d["context"]
                    identity = report_dataset(context)
                    if identity != dataset_key and not (
                        dataset_key == "GPQA" and identity == "GPQA-Diamond"
                    ):
                        continue
                    entries.append(
                        {
                            "report_id": str(report.id),
                            "run_id": str(run.id),
                            "remote_model": context["remote_model"],
                            "created_at": report.created_at.isoformat(),
                            "validity": d["validity"],
                            "summary": d["summary"],
                            "snapshot": context,
                        }
                    )
            data = rank_leaderboard(entries, dataset_key=dataset_key, metric_name=metric_name)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Leaderboard database unavailable") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(503, "Leaderboard source data is invalid") from exc
    return {
        "data": data,
        "excluded_unverified_reports": excluded,
        "request_id": request.state.request_id,
    }
