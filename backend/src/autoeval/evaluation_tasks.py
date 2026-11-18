"""One public task contract; workflow and historical snapshot formats stay private."""

import uuid

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_serializer, model_validator
from sqlalchemy import String, cast, func, or_, select

from autoeval.evaluation.models import EvaluationReport
from autoeval.evaluation.service import (
    evaluation_retry_cleanup,
    evaluation_run_detail,
    evaluation_run_report,
    planned_run_detail,
    planned_run_report,
    submit_planned_run,
)
from autoeval.models import EvaluationRun, RunSnapshot
from autoeval.planning import PlanInput, ResourceRef, TaskInput
from autoeval.responses import Accepted, Envelope, SubmittedRun, TaskListEnvelope, envelope


class TaskSelection(TaskInput):
    concurrency: int | None = Field(default=None, ge=1, le=256)


class SubmitTask(ResourceRef):
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
    dataset_concurrency: int = Field(default=1, ge=1, le=3)

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


router = APIRouter(prefix="/api/autoeval/v1/evaluation-tasks", tags=["evaluation tasks"])
SCOPES = ["local-operator:evaluation", "local-operator:orchestration"]


@router.post("", status_code=202, response_model=Envelope[SubmittedRun])
async def submit(
    body: SubmitTask, request: Request, idempotency_key: str = Header(min_length=1, max_length=256)
):
    # No Planner job/plan ID is accepted. Final parameters are validated and frozen normally.
    inputs = PlanInput(**body.model_dump(), recommend=False)
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
            .outerjoin(EvaluationReport, EvaluationReport.run_id == EvaluationRun.id)
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
        extra = await planned_run_detail(sessions, run_id)
        data.update(
            datasets=extra["datasets"], estimate=extra["estimate"], dataset_report=extra["report"]
        )
        async with sessions() as session:
            frozen = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
            tasks = frozen.canonical_body.get("inputs", {}).get("tasks", [])
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


@router.get("/{run_id}/report", response_model=Envelope[dict])
async def task_report(run_id: uuid.UUID, request: Request):
    sessions = request.app.state.sessions
    async with sessions() as session:
        row = await session.get(EvaluationRun, run_id)
        if not row or row.trigger_scope not in SCOPES:
            raise HTTPException(404, "Evaluation task not found")
        formal = await session.scalar(
            select(EvaluationReport).where(EvaluationReport.run_id == run_id)
        )
        if formal:
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
        return envelope({"accepted": accepted}, request)


@router.post("/{run_id}/cleanup", status_code=202, response_model=Envelope[Accepted])
async def cleanup_task(run_id: uuid.UUID, request: Request):
    data = await evaluation_retry_cleanup(
        request.app.state.sessions, request.app.state.settings, run_id
    )
    return envelope(data, request)


@router.get("/{run_id}/budget", response_model=Envelope[dict])
async def task_budget(run_id: uuid.UUID, request: Request):
    from autoeval.billing import BudgetAccount, BudgetRequest

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
