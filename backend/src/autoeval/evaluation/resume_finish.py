"""Finalize a follow-up round without overwriting the source report."""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select

from autoeval.catalog.datasets import read_manifest
from autoeval.evaluation.models import EvaluationReport, ExecutionRound
from autoeval.evaluation.orchestration import advance_run
from autoeval.infrastructure.models import EvaluationRun, RunSnapshot
from autoeval.reporting.follow_up_reports import build_follow_up_report
from autoeval.reporting.models import CaseExecutionRecord
from autoeval.reporting.task_reports import publish_follow_up_report


async def finish_round(sessions, settings, run_id, round_id, frozen, children, cancelled):
    async with sessions() as session, session.begin():
        run = await session.get_one(EvaluationRun, run_id, with_for_update=True)
        current = await session.scalar(
            select(ExecutionRound)
            .where(ExecutionRound.run_id == run_id)
            .order_by(ExecutionRound.number.desc())
            .limit(1)
        )
        if current is None or current.id != round_id:
            return
        if current.state in {"completed", "failed", "cancelled"}:
            return
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        records = list(
            await session.scalars(
                select(CaseExecutionRecord)
                .where(CaseExecutionRecord.run_id == run_id)
                .order_by(CaseExecutionRecord.attempt_no)
            )
        )
        by_id = {str(record.id): record for record in records}
        selected = defaultdict(list)
        if current.operation == "case_retry":
            await inherit_untouched(session, settings, run_id, records, by_id, selected)
        else:
            for row in current.selection["samples"]:
                if row["category"] == "reusable":
                    selected[(row["dataset_key"], row["sample_id"])] = [
                        by_id[attempt_id] for attempt_id in row["attempt_ids"]
                    ]

        collection_keys = set()
        for child in children:
            if current.operation == "case_retry":
                for sample in child.payload["samples"]:
                    selected.pop((child.payload["dataset"], sample["sample_id"]), None)
            collection_keys.add(f"round-shard:{child.id}")
        for record in records:
            key = (record.tool_metadata or {}).get("execution_collection_key")
            if key in collection_keys:
                selected[(record.dataset_key, record.sample_id)].append(record)

        cancelled = cancelled or run.cancel_requested_at is not None
        historical_state = "cancelled" if cancelled else "completed"
        report_body = await build_follow_up_report(
            settings, run_id, frozen, selected, historical_state
        )
        complete = report_body["validity"] == "complete"
        round_complete = complete
        if current.operation == "case_retry":
            round_complete = bool(children) and all(
                child.state == "succeeded" and (child.summary or {}).get("validity") == "complete"
                for child in children
            )
        current.state = "cancelled" if cancelled else "completed" if round_complete else "failed"
        if cancelled:
            current.cancel_requested_at = run.cancel_requested_at
            current.cancelled_at = datetime.now(UTC)
        task_state = "cancelled" if cancelled else "completed" if complete else "failed"
        if (
            current.operation == "case_retry"
            and not complete
            and current.selection.get("source_state") == "cancelled"
        ):
            task_state = "cancelled"
        report_body["historical_task_state"] = task_state
        report = await publish_follow_up_report(
            session, settings, run_id, current.number, snapshot, report_body
        )
        await advance_run(
            session,
            run,
            task_state,
            {
                "round": current.number,
                "round_state": current.state,
                "report_id": str(report.id),
            },
        )


async def inherit_untouched(session, settings, run_id, records, by_id, selected):
    previous = await session.scalar(
        select(EvaluationReport).where(
            EvaluationReport.run_id == run_id, EvaluationReport.is_current
        )
    )
    if previous is not None and previous.version > 1:
        body = await asyncio.to_thread(read_manifest, settings, previous)
        for dataset in body["datasets"]:
            for case in dataset["case_index"]:
                selected[(dataset["dataset_key"], case["sample_id"])] = [
                    by_id[reference["id"]] for reference in case["attempts"]
                ]
        return
    for record in records:
        if (record.tool_metadata or {}).get(
            "execution_collection_key"
        ) is None and record.state != "started":
            selected[(record.dataset_key, record.sample_id)].append(record)
