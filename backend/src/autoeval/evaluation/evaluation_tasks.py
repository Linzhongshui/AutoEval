"""One public task contract; workflow and historical snapshot formats stay private."""

import uuid
from typing import Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from sqlalchemy import String, cast, func, or_, select

from autoeval.evaluation.models import EvaluationReport, ExecutionRound, ExecutionShard
from autoeval.evaluation.orchestration import child_view
from autoeval.evaluation.resume_preview import preview_scope
from autoeval.evaluation.resume_submission import submit_follow_up
from autoeval.evaluation.service import (
    evaluation_retry_cleanup,
    evaluation_run_detail,
    evaluation_run_report,
    planned_run_detail,
    planned_run_report,
)
from autoeval.evaluation.submission import submit_planned_run
from autoeval.infrastructure.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.infrastructure.responses import (
    Accepted,
    Envelope,
    SubmittedRun,
    TaskListEnvelope,
    envelope,
)
from autoeval.planning.schemas import PerformanceTask, PlanInput, ResourceRef, TaskInput


class TaskSelection(TaskInput):
    concurrency: int | None = Field(default=None, ge=1, le=256)


class SubmitTask(ResourceRef):
    resource_kind: Literal["customer_ssh"]
    resource_ids: list[uuid.UUID] = Field(default_factory=list, max_length=16)
    ignore_budget: bool = Field(default=False, strict=True)

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        value = handler(self)
        if not self.resource_ids:
            value.pop("resource_ids", None)
        if not self.ignore_budget:
            value.pop("ignore_budget", None)
        return value

    target_id: uuid.UUID
    tasks: list[TaskSelection] = Field(min_length=1, max_length=4)
    dataset_concurrency: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def unique_selection(self):
        if self.resource_ids and (
            self.resource_id not in self.resource_ids
            or len(set(self.resource_ids)) != len(self.resource_ids)
        ):
            raise ValueError("Resource pool must be unique and contain the primary resource")
        if len({t.task_id for t in self.tasks}) != len(self.tasks) or len(
            {t.dataset for t in self.tasks}
        ) != len(self.tasks):
            raise ValueError("Duplicate task or dataset")
        return self


class SubmittedTask(BaseModel):
    run_id: str
    state: str


class TaskListItem(BaseModel):
    id: str
    state: str
    created_at: str
    report_id: str | None
    remote_model: str | None
    resource_kind: str | None
    datasets: list[str]
    follow_up_enabled: bool = False


router = APIRouter(prefix="/api/autoeval/v1/evaluation-tasks", tags=["evaluation tasks"])
SCOPES = ["local-operator:evaluation", "local-operator:orchestration"]


class FollowUpConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_round: int = Field(ge=1)
    scope_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CaseRetryConfirmation(FollowUpConfirmation):
    dataset_key: str = Field(min_length=1, max_length=128)
    sample_id: str = Field(min_length=1, max_length=256)


class FollowUpSample(BaseModel):
    dataset_key: str
    sample_id: str
    sample_sha256: str
    has_attempts: bool
    category: str
    reason: str
    attempt_ids: tuple[str, ...]


class FollowUpPreview(BaseModel):
    source_round: int
    operation: str
    target: dict[str, str]
    samples: list[FollowUpSample]
    blockers: list[str]
    warnings: list[str] = Field(default_factory=list)
    sample_count: int
    scope_sha256: str


class FollowUpAccepted(BaseModel):
    run_id: str
    round: int
    target: dict[str, str]


async def follow_up_preview(run_id, request, operation, target):
    async with request.app.state.sessions() as session:
        run = await session.get(EvaluationRun, run_id)
        scope = await preview_scope(session, request.app.state.settings, run, operation, target)
    return envelope({**scope.selection, "scope_sha256": scope.scope_sha256}, request)


@router.get("/{run_id}/resume-preview", response_model=Envelope[FollowUpPreview])
async def resume_preview(run_id: uuid.UUID, request: Request):
    return await follow_up_preview(run_id, request, "resume", {})


@router.get("/{run_id}/case-retry-preview", response_model=Envelope[FollowUpPreview])
async def case_retry_preview(
    run_id: uuid.UUID,
    request: Request,
    dataset_key: str,
    sample_id: str,
):
    target = {"dataset_key": dataset_key, "sample_id": sample_id}
    return await follow_up_preview(run_id, request, "case_retry", target)


async def confirm_follow_up(run_id, request, body, key, operation, target):
    settings = request.app.state.settings
    if not getattr(settings, "evaluation_follow_up_enabled", False):
        raise HTTPException(503, "Follow-up execution is unavailable")

    async def resolve_scope(session, run):
        scope = await preview_scope(session, settings, run, operation, target)
        if scope.selection["blockers"]:
            raise HTTPException(409, detail={"blockers": scope.selection["blockers"]})
        return scope

    async with request.app.state.sessions() as session, session.begin():
        round_row = await submit_follow_up(
            session,
            run_id,
            operation=operation,
            source_number=body.source_round,
            scope_sha256=body.scope_sha256,
            key=key,
            target=target,
            resolve_scope=resolve_scope,
        )
        result = {"run_id": str(run_id), "round": round_row.number, "target": target}
    return envelope(result, request)


@router.post("/{run_id}/resume", status_code=202, response_model=Envelope[FollowUpAccepted])
async def resume_task(
    run_id: uuid.UUID,
    request: Request,
    body: FollowUpConfirmation,
    idempotency_key: str = Header(min_length=1, max_length=256),
):
    return await confirm_follow_up(run_id, request, body, idempotency_key, "resume", {})


@router.post("/{run_id}/case-retry", status_code=202, response_model=Envelope[FollowUpAccepted])
async def retry_case(
    run_id: uuid.UUID,
    request: Request,
    body: CaseRetryConfirmation,
    idempotency_key: str = Header(min_length=1, max_length=256),
):
    target = {"dataset_key": body.dataset_key, "sample_id": body.sample_id}
    return await confirm_follow_up(run_id, request, body, idempotency_key, "case_retry", target)


@router.post("", status_code=202, response_model=Envelope[SubmittedRun])
async def submit(
    body: SubmitTask | PerformanceTask, request: Request, idempotency_key: str = Header(min_length=1, max_length=256)
):
    # No Planner job/plan ID is accepted. Final parameters are validated and frozen normally.
    inputs = body if isinstance(body, PerformanceTask) else PlanInput(**body.model_dump(), recommend=False)
    data = await submit_planned_run(
        request.app.state.sessions,
        request.app.state.settings,
        inputs,
        None,
        idempotency_key,
    )
    return envelope(data, request)


@router.get("", response_model=TaskListEnvelope[TaskListItem])
async def list_tasks(
    request: Request,
    offset: int = 0,
    limit: int = 50,
    state: str | None = None,
    resource_kind: str | None = None,
    query: str = "",
    include_test: bool = False,
):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    body = RunSnapshot.canonical_body
    conditions = [EvaluationRun.trigger_scope.in_(SCOPES)]
    if not include_test:
        conditions += [
            func.coalesce(body["execution_origin"].astext, "unverified") == "real",
            ~func.coalesce(body["remote_model"].astext, "").bool_op("~*")(
                "^(test|fixture|browser|simulation)([-_:]|$)"
            ),
            ~EvaluationRun.created_by.bool_op("~*")("^(test|fixture|browser)([-_:]|$)"),
        ]
    if state == "active":
        conditions.append(EvaluationRun.state.notin_(["completed", "failed", "cancelled"]))
    elif state:
        conditions.append(EvaluationRun.state == state)
    if resource_kind:
        conditions.append(body["resource_kind"].astext == resource_kind)
    if query.strip():
        term = (
            "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        conditions.append(
            or_(
                cast(EvaluationRun.id, String).ilike(term, escape="\\"),
                body["remote_model"].astext.ilike(term, escape="\\"),
            )
        )
    async with request.app.state.sessions() as session:
        base = (
            select(EvaluationRun, RunSnapshot, EvaluationReport.id)
            .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
            .outerjoin(
                EvaluationReport,
                (EvaluationReport.run_id == EvaluationRun.id) & EvaluationReport.is_current,
            )
            .where(*conditions)
        )
        counts = (
            await session.execute(
                select(EvaluationRun.state, func.count())
                .join(RunSnapshot, RunSnapshot.run_id == EvaluationRun.id)
                .where(*conditions)
                .group_by(EvaluationRun.state)
            )
        ).all()
        statistics = {
            "total": sum(n for _, n in counts),
            "active": 0,
            "completed": 0,
            "failed_cancelled": 0,
        }
        for status, n in counts:
            statistics[
                "completed"
                if status == "completed"
                else "failed_cancelled"
                if status in {"failed", "cancelled"}
                else "active"
            ] += n
        rows = (
            await session.execute(
                base.order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
        return {
            **envelope(
                [
                    {
                        "id": str(r.id),
                        "state": r.state,
                        "created_at": r.created_at.isoformat(),
                        "report_id": str(report_id) if report_id else None,
                        "remote_model": s.canonical_body.get("remote_model"),
                        "resource_kind": s.canonical_body.get("resource_kind"),
                        "follow_up_enabled": (
                            s.schema_version == "planned-run.v1"
                            and not s.canonical_body.get("inputs", {}).get("performance")
                            and bool(s.canonical_body.get("inputs", {}).get("tasks"))
                            and getattr(
                                request.app.state.settings, "evaluation_follow_up_enabled", False
                            )
                        ),
                        "datasets": [
                            t["dataset"]
                            for t in s.canonical_body.get("inputs", {}).get("tasks", [])
                        ]
                        or [s.canonical_body.get("dataset_key", "GPQA")],
                    }
                    for r, s, report_id in rows[:limit]
                ],
                request,
            ),
            "statistics": statistics,
            "next_offset": offset + limit if len(rows) > limit else None,
        }


@router.get("/{run_id}", response_model=Envelope[dict])
async def task_detail(run_id: uuid.UUID, request: Request):
    sessions = request.app.state.sessions
    async with sessions() as session:
        row = await session.get(EvaluationRun, run_id)
        if not row or row.trigger_scope not in SCOPES:
            raise HTTPException(404, "Evaluation task not found")
        scope = row.trigger_scope
    data = await evaluation_run_detail(sessions, request.app.state.settings, run_id)
    if scope == "local-operator:orchestration":
        data["follow_up_enabled"] = getattr(
            request.app.state.settings, "evaluation_follow_up_enabled", False
        )
        extra = await planned_run_detail(sessions, run_id)
        data.update(
            datasets=extra["datasets"], estimate=extra["estimate"], dataset_report=extra["report"]
        )
        async with sessions() as session:
            frozen = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
            tasks = frozen.canonical_body.get("inputs", {}).get("tasks", [])
            if frozen.canonical_body.get("task_type") == "performance":
                data["follow_up_enabled"] = False
            else:
                await project_follow_up_detail(session, run_id, data, tasks)
            data["snapshot"]["dataset_configurations"] = [
                {
                    **{
                        k: t.get(k)
                        for k in (
                            "dataset",
                            "compilation_id",
                            "manifest_id",
                            "manifest_sha256",
                            "concurrency",
                            "tool",
                        )
                    },
                    "config": t.get("compilation", {}).get("config"),
                }
                for t in tasks
            ]
    else:
        snap = data.get("snapshot") or {}
        data["datasets"] = [
            {
                "id": str(run_id),
                "dataset": snap.get("dataset_key", "GPQA"),
                "state": data["state"],
                "summary": (data.get("report") or {}).get("summary"),
                "actual_duration_sec": None,
                "started_at": None,
                "finished_at": None,
            }
        ]
    return envelope(data, request)


async def project_follow_up_detail(session, run_id, data, tasks):
    current = await session.scalar(
        select(ExecutionRound)
        .where(ExecutionRound.run_id == run_id)
        .order_by(ExecutionRound.number.desc())
        .limit(1)
    )
    if current is None:
        return
    data["current_round"] = current.number
    report = await session.scalar(
        select(EvaluationReport).where(
            EvaluationReport.run_id == run_id,
            EvaluationReport.is_current,
            EvaluationReport.version == current.number,
        )
    )
    summaries = {
        dataset["dataset_key"]: dataset["summary"]
        for dataset in (report.summary.get("dataset_results", []) if report else [])
    }
    shards = list(
        await session.scalars(
            select(ExecutionShard)
            .where(ExecutionShard.round_id == current.id)
            .order_by(ExecutionShard.position)
        )
    )
    original = {dataset["task_id"]: dataset for dataset in data["datasets"]}
    data["datasets"] = [original[task["task_id"]] for task in tasks if task["task_id"] in original]
    for task in tasks:
        name = task["dataset"]
        dataset = original.get(task["task_id"])
        if dataset is None:
            continue
        if name in summaries:
            summary = summaries[name]
            dataset["summary"] = summary
            dataset["state"] = (
                "succeeded"
                if summary["validity"] == "complete"
                else ("cancelled" if data["state"] == "cancelled" else "failed")
            )
            continue
        children = [shard for shard in shards if shard.task_id == task["task_id"]]
        if not children and current.operation != "resume":
            continue
        reused = sum(
            sample["dataset_key"] == name and sample["category"] == "reusable"
            for sample in current.selection["samples"]
            if current.operation == "resume"
        )
        dataset["state"] = next(
            (
                state
                for state in (
                    "unresolved",
                    "running",
                    "submitting",
                    "pending",
                    "failed",
                    "cancelled",
                )
                if any(shard.state == state for shard in children)
            ),
            "succeeded",
        )
        dataset["summary"] = {
            "expected_cases": len(task["samples"]),
            "observed_cases": reused
            + sum((shard.summary or {}).get("observed_cases", 0) for shard in children),
            "reused_cases": reused,
        }
    if report:
        data["dataset_report"] = {"round": current.number, "report_id": str(report.id)}


@router.get("/{run_id}/rounds", response_model=Envelope[dict])
async def task_rounds(run_id: uuid.UUID, request: Request):
    async with request.app.state.sessions() as session:
        run = await session.get(EvaluationRun, run_id)
        if not run or run.trigger_scope != "local-operator:orchestration":
            raise HTTPException(404, "Evaluation task not found")
        rounds = list(
            await session.scalars(
                select(ExecutionRound)
                .where(ExecutionRound.run_id == run_id)
                .order_by(ExecutionRound.number)
            )
        )
        reports = {
            report.version: str(report.id)
            for report in await session.scalars(
                select(EvaluationReport).where(EvaluationReport.run_id == run_id)
            )
        }
        shards = {}
        if rounds:
            for shard in await session.scalars(
                select(ExecutionShard)
                .where(ExecutionShard.round_id.in_([r.id for r in rounds]))
                .order_by(ExecutionShard.position)
            ):
                shards.setdefault(shard.round_id, []).append(child_view(shard))
        first_state = run.state
        first_cancel = run.cancel_requested_at
        if rounds:
            event = await session.scalar(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.type == "follow_up_queued")
                .order_by(RunEvent.seq)
                .limit(1)
            )
            first_state = event.body.get("source_state") if event else None
            first_cancel = event.body.get("source_cancel_requested_at") if event else None
        data = [
            {
                "number": 1,
                "operation": "initial",
                "state": first_state,
                "cancel_requested_at": first_cancel,
                "report_id": reports.get(1),
            }
        ]
        data.extend(
            {
                "number": row.number,
                "operation": row.operation,
                "state": row.state,
                "target": row.selection.get("target"),
                "cancel_requested_at": row.cancel_requested_at,
                "cancelled_at": row.cancelled_at,
                "report_id": reports.get(row.number),
                "shards": shards.get(row.id, []),
            }
            for row in rounds
        )
    return envelope({"rounds": data}, request)


@router.get("/{run_id}/report", response_model=Envelope[dict])
async def task_report(run_id: uuid.UUID, request: Request):
    sessions = request.app.state.sessions
    async with sessions() as session:
        row = await session.get(EvaluationRun, run_id)
        if not row or row.trigger_scope not in SCOPES:
            raise HTTPException(404, "Evaluation task not found")
        formal = await session.scalar(
            select(EvaluationReport).where(
                EvaluationReport.run_id == run_id, EvaluationReport.is_current
            )
        )
        if formal:
            if formal.version > 1:
                from autoeval.reporting.report_integrity import verified_report_body

                snapshot = await session.scalar(
                    select(RunSnapshot).where(RunSnapshot.run_id == run_id)
                )
                status, body = await verified_report_body(
                    request.app.state.settings, formal, row, snapshot
                )
                if status != "verified":
                    raise HTTPException(
                        503, "Report evidence unavailable or integrity check failed"
                    )
                return envelope(body, request)
            import asyncio

            from autoeval.catalog.datasets import read_manifest

            try:
                return envelope(
                    await asyncio.to_thread(read_manifest, request.app.state.settings, formal),
                    request,
                )
            except (BotoCoreError, ClientError, ValueError) as exc:
                raise HTTPException(
                    503, "Report evidence unavailable or integrity check failed"
                ) from exc
        grouped = row.trigger_scope == "local-operator:orchestration"
    try:
        data = (
            await planned_run_report(sessions, request.app.state.settings, run_id)
            if grouped
            else await evaluation_run_report(sessions, request.app.state.settings, run_id)
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(503, "Report evidence unavailable or integrity check failed") from exc
    return envelope(data, request)


@router.post("/{run_id}/cancel", status_code=202, response_model=Envelope[Accepted])
async def cancel_task(run_id: uuid.UUID, request: Request):
    from datetime import UTC, datetime

    async with request.app.state.sessions() as session, session.begin():
        row = await session.get(EvaluationRun, run_id, with_for_update=True)
        if not row or row.trigger_scope not in SCOPES:
            raise HTTPException(404, "Evaluation task not found")
        accepted = row.state not in {"completed", "failed", "cancelled"}
        if accepted and row.cancel_requested_at is None:
            row.cancel_requested_at = datetime.now(UTC)
            current_round = await session.scalar(
                select(ExecutionRound)
                .where(ExecutionRound.run_id == run_id)
                .order_by(ExecutionRound.number.desc())
                .limit(1)
            )
            if current_round is not None:
                current_round.cancel_requested_at = row.cancel_requested_at
        return envelope({"accepted": accepted}, request)


@router.post("/{run_id}/cleanup", status_code=202, response_model=Envelope[Accepted])
async def cleanup_task(run_id: uuid.UUID, request: Request):
    data = await evaluation_retry_cleanup(
        request.app.state.sessions, request.app.state.settings, run_id
    )
    return envelope(data, request)


@router.get("/{run_id}/budget", response_model=Envelope[dict])
async def task_budget(run_id: uuid.UUID, request: Request):
    from autoeval.billing.models import BudgetAccount, BudgetRequest

    async with request.app.state.sessions() as db:
        run = await db.get(EvaluationRun, run_id)
        if run is None or run.trigger_scope not in SCOPES:
            raise HTTPException(404, "Evaluation task not found")
        snapshot = await db.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        frozen = snapshot.canonical_body.get("model_budget") if snapshot else None
        if not frozen:
            return envelope({"state": "not_configured"}, request)
        if frozen.get("mode") == "ignored":
            return envelope(
                {
                    "state": "ignored",
                    "limits_applied": False,
                    "acknowledged_at": frozen["acknowledged_at"],
                    "execution_deadline": frozen["execution_deadline"],
                },
                request,
            )
        account = await db.get(BudgetAccount, uuid.UUID(frozen["budget_id"]))
        if account is None:
            raise HTTPException(409, "Frozen budget account missing")
        unresolved = await db.scalar(
            select(func.count())
            .select_from(BudgetRequest)
            .where(BudgetRequest.budget_id == account.id, BudgetRequest.state == "unresolved")
        )
        return envelope(
            {
                "budget_id": str(account.id),
                "currency": account.currency,
                "total_limit": str(account.total_limit),
                "evaluation_limit": str(account.evaluation_limit),
                "analysis_limit": str(account.analysis_limit),
                "reserved": str(account.reserved),
                "spent_upper_bound": str(account.spent),
                "remaining": str(account.total_limit - account.reserved - account.spent),
                "state": account.state,
                "deadline": frozen["deadline"],
                "unresolved_requests": unresolved,
                "cost_basis": "conservative_official_upper_bound_not_provider_invoice",
            },
            request,
        )
