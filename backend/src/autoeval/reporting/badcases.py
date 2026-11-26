"""Compare one report's cases with approved history that shares the exact config.

The scoring adapts the T1 branch of the harbor badcase skill: hard signals, a
Beta-Binomial shrinkage pass rate, and an explicit low-confidence fallback when
no approved same-config history exists. IRT and cross-config neighbour voting
are intentionally out of scope because history is restricted to the same model
service and execution conditions.
"""

import hashlib
import math
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from autoeval.catalog.dataset_identity import report_dataset
from autoeval.catalog.datasets import canonical_manifest, read_manifest
from autoeval.evaluation.models import EvaluationReport
from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
from autoeval.reporting.models import CaseExecutionRecord
from autoeval.reporting.report_integrity import verified_report_body
from autoeval.reporting.unified_outputs import parse_output

ALPHA = 1.0
BETA = 1.0
MIN_HISTORY = 3
P_THRESHOLD = 0.5
SOFT_WEIGHT = 0.25
SOFT_CAP = 2.0
BAND_RANK = {"high": 2, "low": 1, "non_badcase": 0}

router = APIRouter(prefix="/api/autoeval/v1", tags=["badcase comparison"])


def canonical_dataset(context):
    identity = report_dataset(context)
    # The platform currently evaluates GPQA-Diamond under both dataset_key spellings.
    return "GPQA-Diamond" if identity in {"GPQA", "GPQA-Diamond"} else identity


def context_tasks(context):
    tasks = (context.get("inputs") or {}).get("tasks") or []
    return tasks if isinstance(tasks, list) else []


def section_samples(context):
    task = context_tasks(context)
    samples = context.get("samples") or (task[0].get("samples") if len(task) == 1 else []) or []
    return [sample["sample_id"] for sample in samples if isinstance(sample, dict)]


def config_view(context):
    task = context_tasks(context)
    task = task[0] if len(task) == 1 else None
    frozen = context.get("parameters") or {}
    if task:
        params = ((task.get("compilation") or {}).get("config") or {}).get("params") or {}
        generation = params.get("generation_kwargs", params.get("sampling_args", {})) or {}
        output = params.get("max_out_len", generation.get("max_tokens"))
        temperature = generation.get("temperature")
        top_p = generation.get("top_p")
        concurrency = task.get("concurrency")
        scope = task.get("subset_scope")
        manifest_sha256 = task.get("manifest_sha256")
        tool_revision = (task.get("tool") or {}).get("revision")
    else:
        output = frozen.get("output")
        temperature = frozen.get("temperature")
        top_p = frozen.get("top_p")
        concurrency = frozen.get("concurrency")
        scope = frozen.get("scope")
        manifest_sha256 = context.get("manifest_sha256")
        tool_revision = (context.get("tool") or {}).get("revision")
    return {
        "remote_model": context.get("remote_model"),
        "target_id": context.get("target_id"),
        "manifest_sha256": manifest_sha256,
        "tool_revision": tool_revision,
        "output": output,
        "concurrency": concurrency,
        "temperature": temperature,
        "top_p": top_p,
        "scope": str(scope).lower() if scope is not None else None,
    }


def config_signature(config):
    raw = canonical_manifest(config)
    return hashlib.sha256(raw).hexdigest()


def same_config(left, right):
    keys = (
        "remote_model",
        "manifest_sha256",
        "tool_revision",
        "output",
        "concurrency",
        "temperature",
        "top_p",
        "scope",
    )
    if any(left.get(key) != right.get(key) for key in keys):
        return False
    # A frozen target identity is required: the same model name on another
    # endpoint is not comparable history.
    if not left.get("target_id") or not right.get("target_id"):
        return False
    return left["target_id"] == right["target_id"]


def dataset_keys_for(dataset_key):
    """Physical dataset spellings accepted for one canonical dataset."""
    if dataset_key == "GPQA-Diamond":
        return {"GPQA", "GPQA_diamond", "GPQA-Diamond"}
    return {dataset_key} if dataset_key else set()


def section_task(context):
    tasks = context_tasks(context)
    return tasks[0] if len(tasks) == 1 else None


def section_subcommand(context):
    task = section_task(context)
    if task:
        return (((task.get("compilation") or {}).get("config") or {}).get("subcommand"))
    return context.get("subcommand")


def section_dataset_key(context):
    task = section_task(context)
    return task.get("dataset") if task else context.get("dataset_key")


def section_cases(context, archive, settings):
    """Return (case map, from_archive) for one dataset section."""
    sample_ids = section_samples(context)
    dataset_key = section_dataset_key(context)
    if archive:
        row = SimpleNamespace(object_key=archive["object_key"], sha256=archive["sha256"])
        body = read_manifest(settings, row)
        cases, _ = parse_output(
            canonical_manifest(body),
            {dataset_key: sample_ids},
            dataset_key,
        )
        latest = {}
        for case in cases:
            latest[case["sample_id"]] = case
        return latest, True
    return {}, False


def record_view(row, trace_status="unsupported"):
    metadata = row.tool_metadata if isinstance(row.tool_metadata, dict) else {}
    score = metadata.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
        score = None
    return {
        "score": score,
        "state": row.state,
        "attempt_no": row.attempt_no,
        "error_code": row.error_code,
        "has_evidence": row.sha256 is not None,
        "evidence_status": "available" if row.sha256 is not None else "unavailable",
        "score_status": "scored" if score is not None else "missing",
        "missing": False,
        "trace_status": trace_status,
        "input_tokens": metadata.get("input_tokens"),
        "output_tokens": metadata.get("output_tokens"),
        "duration_sec": metadata.get("duration_sec"),
        "tool_started_at": metadata.get("tool_started_at"),
        "tool_finished_at": metadata.get("tool_finished_at"),
        "status": metadata.get("status"),
    }


def missing_case():
    return {
        "score": None,
        "state": "missing",
        "attempt_no": 0,
        "error_code": None,
        "has_evidence": False,
        "evidence_status": "unavailable",
        "score_status": "missing",
        "missing": True,
        "trace_status": "unsupported",
        "input_tokens": None,
        "output_tokens": None,
        "duration_sec": None,
        "tool_started_at": None,
        "tool_finished_at": None,
        "status": "missing",
    }


async def latest_records(session, run_id, sample_ids, dataset_keys=None):
    if not sample_ids:
        return {}
    query = select(CaseExecutionRecord).where(
        CaseExecutionRecord.run_id == run_id,
        CaseExecutionRecord.sample_id.in_(sample_ids),
    )
    if dataset_keys:
        query = query.where(CaseExecutionRecord.dataset_key.in_(sorted(dataset_keys)))
    rows = (
        await session.scalars(
            query.order_by(CaseExecutionRecord.attempt_no)
        )
    ).all()
    latest = {}
    for row in rows:
        latest[row.sample_id] = row
    return latest


async def trace_statuses(session, rows):
    if not rows:
        return {}
    from autoeval.reporting.langfuse_integration import TraceImport

    imports = (
        await session.scalars(
            select(TraceImport).where(TraceImport.attempt_id.in_([row.id for row in rows]))
        )
    ).all()
    return {row.attempt_id: row.status for row in imports}


async def dataset_cases(session, settings, run_id, context, archive, dataset_key):
    sample_ids = section_samples(context)
    try:
        cases, from_archive = await _section_cases_async(settings, context, archive)
    except (ValueError, KeyError, TypeError, OSError):
        cases, from_archive = {}, False
    records = await latest_records(
        session, run_id, sample_ids, dataset_keys_for(dataset_key)
    )
    statuses = await trace_statuses(session, list(records.values()))
    result = {}
    for sample_id in sample_ids:
        record = records.get(sample_id)
        if record is not None:
            current = record_view(record, statuses.get(record.id, "unsupported"))
            if sample_id in cases:
                current["score"] = cases[sample_id]["score"]
                current["attempt_no"] = cases[sample_id]["attempt_no"]
                current["has_evidence"] = True
                current["evidence_status"] = "available"
                current["score_status"] = (
                    "scored" if cases[sample_id]["score"] is not None else "missing"
                )
            result[sample_id] = current
        elif sample_id in cases:
            case = cases[sample_id]
            result[sample_id] = {
                "score": case["score"],
                "state": "succeeded" if case["status"] == "success" else "failed",
                "attempt_no": case["attempt_no"],
                "error_code": None,
                "has_evidence": True,
                "evidence_status": "available",
                "score_status": "scored" if case["score"] is not None else "missing",
                "missing": False,
                "trace_status": "unsupported",
                "input_tokens": case["input_tokens"],
                "output_tokens": case["output_tokens"],
                "duration_sec": case["duration_sec"],
                "tool_started_at": case["tool_started_at"],
                "tool_finished_at": case["tool_finished_at"],
                "status": case["status"],
            }
        else:
            result[sample_id] = missing_case()
    return result, from_archive or bool(cases)


async def _section_cases_async(settings, context, archive):
    if not archive:
        return {}, False
    import asyncio

    return await asyncio.to_thread(section_cases, context, archive, settings)


def history_stats(entries):
    scores = [entry["score"] for entry in entries if entry.get("score") is not None]
    n = len(scores)
    k = sum(1 for score in scores if score >= 1)
    return {
        "n": n,
        "k": k,
        "mean": round(sum(scores) / n, 4) if n else None,
        "scores": entries,
    }


def soft_signals(current, subcommand):
    failures = (
        current["state"] == "failed"
        or current["error_code"]
        or current["score"] is None
        or current["score"] < 1
    )
    if not failures:
        return []
    signals = []
    if current.get("input_tokens") is None and current.get("output_tokens") is None:
        signals.append("no-tokens")
    if not current.get("has_evidence"):
        signals.append("no-evidence")
    if subcommand == "harbor_agent":
        if current.get("trace_status") not in {"succeeded"}:
            signals.append("no-trace")
        if current.get("duration_sec") is None:
            signals.append("no-duration")
    return signals


def verdict(current, stats, signals, subcommand):
    multiplier = round(min(SOFT_CAP, 1.0 + SOFT_WEIGHT * len(signals)), 4)
    if current.get("missing"):
        return {
            "is_badcase": False,
            "band": "non_badcase",
            "suspicion": 0.0,
            "method": "missing",
            "confidence": "missing",
            "p_hat": None,
            "hard_signals": [],
            "soft_signals": [],
            "multiplier": 1.0,
            "why_not_badcase": "missing_execution：清单内没有执行记录，不纳入模型能力判定",
            "reasons": ["清单内缺测，不纳入模型能力判定"],
        }
    hard = []
    if current["state"] == "failed":
        hard.append("execution-failed")
    if current.get("error_code"):
        hard.append("exception:" + current["error_code"])
    if current.get("score") is None:
        hard.append("score-missing")
    reason_prefix = "执行异常：" + ", ".join(hard) if hard else None

    if hard:
        return {
            "is_badcase": True,
            "band": "high",
            "suspicion": round(1.0 * multiplier, 4),
            "method": "hard",
            "confidence": "hard",
            "p_hat": 0.0,
            "hard_signals": hard,
            "soft_signals": signals,
            "multiplier": multiplier,
            "why_not_badcase": None,
            "reasons": [reason_prefix],
        }

    passed = current.get("score") is not None and current["score"] >= 1
    if passed:
        if not current.get("has_evidence"):
            return {
                "is_badcase": False,
                "band": "low",
                "suspicion": round(0.5 * multiplier, 4),
                "method": "suspicious_pass",
                "confidence": "suspicious-pass",
                "p_hat": None,
                "hard_signals": [],
                "soft_signals": signals,
                "multiplier": multiplier,
                "why_not_badcase": None,
                "reasons": ["本次通过但缺少执行证据，需人工核验"],
            }
        return {
            "is_badcase": False,
            "band": "non_badcase",
            "suspicion": 0.0,
            "method": "pass",
            "confidence": "pass",
            "p_hat": None,
            "hard_signals": [],
            "soft_signals": signals,
            "multiplier": multiplier,
            "why_not_badcase": None,
            "reasons": ["本次通过"],
        }

    n = stats["n"]
    if n == 0:
        return {
            "is_badcase": True,
            "band": "low",
            "suspicion": round(0.5 * multiplier, 4),
            "method": "fallback",
            "confidence": "fallback/no-history",
            "p_hat": None,
            "hard_signals": [],
            "soft_signals": signals,
            "multiplier": multiplier,
            "why_not_badcase": None,
            "reasons": ["没有同配置已审核历史，仅做失败复盘，不能推断本不该失败"],
        }

    p_hat = (stats["k"] + ALPHA) / (n + ALPHA + BETA)
    is_badcase = p_hat >= P_THRESHOLD
    if is_badcase:
        band = "high" if p_hat <= P_THRESHOLD else "low"
        confidence = "T1/exact" if n >= MIN_HISTORY else "T1/low-n"
        reasons = [f"同配置历史通过率 {p_hat:.1%}，本次未通过"]
        if n < MIN_HISTORY:
            reasons.append(f"历史仅 {n} 条，低置信")
        return {
            "is_badcase": True,
            "band": band,
            "suspicion": round((1.0 - p_hat) * multiplier, 4),
            "method": "T1",
            "confidence": confidence,
            "p_hat": round(p_hat, 4),
            "hard_signals": [],
            "soft_signals": signals,
            "multiplier": multiplier,
            "why_not_badcase": None,
            "reasons": reasons,
        }
    return {
        "is_badcase": False,
        "band": "non_badcase",
        "suspicion": 0.0,
        "method": "T1",
        "confidence": "T1/exact" if n >= MIN_HISTORY else "T1/low-n",
        "p_hat": round(p_hat, 4),
        "hard_signals": [],
        "soft_signals": signals,
        "multiplier": multiplier,
        "why_not_badcase": (
            f"low-expected-pass-rate: p_hat={p_hat:.4f} < {P_THRESHOLD:.2f}，"
            "该题对当前配置本就期望失败"
        ),
        "reasons": [f"同配置历史通过率 {p_hat:.1%}，属预期失败"],
    }


def sort_cases(cases):
    return sorted(
        cases,
        key=lambda item: (
            -BAND_RANK[item["verdict"]["band"]],
            -item["verdict"]["suspicion"],
            item["sample_id"],
        ),
    )


def report_sections(report, snapshot, body):
    if body.get("schema_version") == "task-report.v2":
        return body.get("datasets") or []
    context = snapshot.canonical_body
    return [
        {
            "dataset_key": canonical_dataset(context),
            "summary": report.summary,
            "validity": report.validity,
            "context": context,
            "archive": None,
        }
    ]


async def comparison(session, settings, run_id):
    report = await session.scalar(select(EvaluationReport).where(EvaluationReport.run_id == run_id))
    if report is None:
        raise HTTPException(409, "report_not_published")
    run = await session.get(EvaluationRun, run_id)
    snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
    if run is None or snapshot is None:
        raise HTTPException(409, "report_evidence_unverified")
    current_status, body = await verified_report_body(settings, report, run, snapshot)
    if current_status != "verified" or body is None:
        raise HTTPException(409, "report_evidence_unverified")

    current_sections = report_sections(report, snapshot, body)
    history_rows = (
        await session.execute(
            select(EvaluationReport, EvaluationRun, RunSnapshot)
            .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
            .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
            .where(
                EvaluationReport.run_id != run_id,
                EvaluationReport.review_status == "approved",
                EvaluationReport.execution_origin == "real",
                EvaluationReport.validity == "complete",
            )
            .order_by(EvaluationReport.created_at)
        )
    ).all()

    datasets = []
    for section in current_sections:
        context = section["context"]
        dataset_key = canonical_dataset(context)
        config = config_view(context)
        history_reports = []
        history_scores = {}
        for history_report, history_run, history_snapshot in history_rows:
            if history_report.execution_origin != "real":
                continue
            status, history_body = await verified_report_body(
                settings, history_report, history_run, history_snapshot
            )
            if status != "verified" or history_body is None:
                continue
            for history_section in report_sections(history_report, history_snapshot, history_body):
                history_context = history_section["context"]
                if canonical_dataset(history_context) != dataset_key:
                    continue
                if not same_config(config, config_view(history_context)):
                    continue
                if str(history_report.id) in history_reports:
                    continue
                try:
                    history_cases, _ = await _section_cases_async(
                        settings, history_context, history_section.get("archive")
                    )
                except (ValueError, KeyError, TypeError, OSError):
                    history_cases = {}
                if not history_cases:
                    history_cases, _ = await _fallback_cases(
                        session, history_report.run_id, history_context, dataset_key
                    )
                history_reports.append(str(history_report.id))
                for sample_id, case in history_cases.items():
                    if case.get("score") is None:
                        continue
                    history_scores.setdefault(sample_id, []).append(
                        {
                            "report_id": str(history_report.id),
                            "run_id": str(history_report.run_id),
                            "created_at": history_report.created_at.isoformat(),
                            "score": case["score"],
                        }
                    )

        current_cases, _ = await dataset_cases(
            session, settings, run_id, context, section.get("archive"), dataset_key
        )
        if not current_cases:
            current_cases, _ = await _fallback_cases(
                session, run_id, context, dataset_key
            )
        subcommand = section_subcommand(context)
        rows = []
        for sample_id, current in current_cases.items():
            stats = history_stats(history_scores.get(sample_id, []))
            signals = soft_signals(current, subcommand)
            result = verdict(current, stats, signals, subcommand)
            delta = (
                round(current["score"] - stats["mean"], 4)
                if current.get("score") is not None and stats["mean"] is not None
                else None
            )
            rows.append(
                {
                    "sample_id": sample_id,
                    "current": current,
                    "history": stats,
                    "delta": delta,
                    "verdict": result,
                }
            )
        rows = sort_cases(rows)
        counts = {
            "total": len(rows),
            "high": 0,
            "low": 0,
            "non_badcase": 0,
            "missing": 0,
        }
        for row in rows:
            counts[row["verdict"]["band"]] += 1
            if row["current"].get("missing"):
                counts["missing"] += 1
        datasets.append(
            {
                "dataset_key": dataset_key,
                "config": {**config, "signature_sha256": config_signature(config)},
                "history": {
                    "approved_reports": len(set(history_reports)),
                    "report_ids": sorted(set(history_reports)),
                },
                "summary": counts,
                "cases": rows,
            }
        )

    return {
        "run_id": str(run_id),
        "report_id": str(report.id),
        "generated_at": datetime.now(UTC).isoformat(),
        "report": {
            "validity": report.validity,
            "evidence_status": current_status,
            "review_status": report.review_status,
            "remote_model": snapshot.canonical_body.get("remote_model"),
            "created_at": report.created_at.isoformat(),
        },
        "algorithm": {
            "name": "beta-binomial-t1",
            "alpha": ALPHA,
            "beta": BETA,
            "min_history": MIN_HISTORY,
            "p_threshold": P_THRESHOLD,
        },
        "datasets": datasets,
    }


async def _fallback_cases(session, run_id, context, dataset_key):
    sample_ids = section_samples(context)
    records = await latest_records(
        session, run_id, sample_ids, dataset_keys_for(dataset_key)
    )
    statuses = await trace_statuses(session, list(records.values()))
    cases = {}
    for sample_id, record in records.items():
        cases[sample_id] = record_view(record, statuses.get(record.id, "unsupported"))
    return cases, False


async def report_case(session, settings, run_id, dataset_key, sample_id, attempt_no=None):
    """Load one normalized case (including its raw inference payload) for export."""
    report = await session.scalar(select(EvaluationReport).where(EvaluationReport.run_id == run_id))
    if report is None:
        return None
    run = await session.get(EvaluationRun, run_id)
    snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
    if run is None or snapshot is None:
        return None
    status, body = await verified_report_body(settings, report, run, snapshot)
    if status != "verified" or body is None:
        return None
    for section in report_sections(report, snapshot, body):
        if canonical_dataset(section["context"]) != dataset_key:
            continue
        try:
            cases, _ = await _section_cases_async(
                settings, section["context"], section.get("archive")
            )
        except (ValueError, KeyError, TypeError, OSError):
            cases = {}
        if not cases:
            cases, _ = await _fallback_cases(
                session, run_id, section["context"], dataset_key
            )
        for case in cases.values():
            if case["sample_id"] != sample_id:
                continue
            if attempt_no is not None and case["attempt_no"] != attempt_no:
                continue
            return case
    return None


@router.get("/runs/{run_id}/badcase-comparison")
async def badcase_comparison(run_id: uuid.UUID, request: Request):
    try:
        async with request.app.state.sessions() as session:
            data = await comparison(session, request.app.state.settings, run_id)
        return {"data": data, "request_id": request.state.request_id}
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Badcase comparison database unavailable") from exc
