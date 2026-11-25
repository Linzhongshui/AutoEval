# ruff: noqa: PLC0414 -- explicit compatibility re-exports
"""Persistent planning intents. Workers own calculations and remote generation probes."""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from autoeval.catalog.datasets import DatasetManifest
from autoeval.catalog.standard_inputs import (
    StandardInputCompilation,
    StandardInputVersion,
    digest,
    reject_secrets,
)
from autoeval.evaluation.inputs import resolve_inputs, target_data
from autoeval.evaluation.service import (
    planned_run_detail,
    planned_run_report,
)
from autoeval.evaluation.submission import submit_planned_run
from autoeval.infrastructure.responses import (
    Accepted,
    Envelope,
    ObjectPageEnvelope,
    PageEnvelope,
    SubmittedRun,
    envelope,
)
from autoeval.planning.artifacts import artifact, current_preflight
from autoeval.planning.models import PlanningArtifact, PlanningJob
from autoeval.planning.planning_engine import DATASETS, apply_concurrency
from autoeval.planning.schemas import (
    ApplyInput,
    CurveInput,
    PerformanceTask,
    PlanInput,
    ProbeInput,
    Strict,
)
from autoeval.planning.schemas import ResourceRef as ResourceRef
from autoeval.planning.schemas import TaskInput as TaskInput


class IdOnly(BaseModel):
    id: str


class JobAccepted(BaseModel):
    id: str
    state: str
    result: dict | None = None


class JobStatus(BaseModel):
    id: str
    kind: str
    state: str
    result: dict | None
    cancel_requested: bool
    created_at: str
    updated_at: str


class ProbeReconciled(BaseModel):
    id: str
    state: str
    created_at: str
    updated_at: str
    result: dict | None


class CompilationOption(BaseModel):
    id: str
    dataset: str | None
    label: str
    sha256: str
    adaptor_revision: str | None
    runtime_config: dict
    target_id: str | None
    config: dict
    input_ready: bool | None


class ManifestOption(BaseModel):
    id: str
    scope: str
    sample_count: int
    sha256: str
    dataset: str


class CurveOption(BaseModel):
    id: str
    target_id: Any = None
    resource_id: Any = None
    resource_kind: Any = None
    measured_at: Any = None


class PlanningOptions(BaseModel):
    compilations: list[CompilationOption]
    manifests: list[ManifestOption]
    curves: list[CurveOption]


class PlannedRunItem(BaseModel):
    id: str
    state: str
    created_at: str


class PlannedRunDetail(BaseModel):
    report_id: str | None
    id: str
    state: str
    estimate: Any = None
    datasets: list[dict]
    report: dict | None
    execution_origin: Any = None


class AppliedPlan(BaseModel):
    execution_plan_id: str
    sha256: str
    report: dict


router = APIRouter(prefix="/api/autoeval/v1/planning", tags=["task planning"])

@router.get("/options", response_model=ObjectPageEnvelope[PlanningOptions])
async def options(request: Request, offset: int = 0, limit: int = 100, include_test: bool = False):
    from autoeval.catalog.models import EvaluationProfile

    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    async with request.app.state.sessions() as session:
        compilations = list(
            await session.scalars(
                select(StandardInputCompilation)
                .where(StandardInputCompilation.id.notin_(request.app.state.settings.archived_compilation_ids))
                .order_by(StandardInputCompilation.created_at.desc(), StandardInputCompilation.id)
                .offset(offset)
                .limit(limit + 1)
            )
        )
        profiles = list(
            await session.scalars(
                select(EvaluationProfile)
                .where(EvaluationProfile.dataset_name.in_(DATASETS))
                .where(
                    True
                    if include_test
                    else ~EvaluationProfile.profile_key.op("~")(
                        r"^(fixture-[a-f0-9]{32}|browser-[a-f0-9]{12}|pipeline-[a-f0-9]{32})$"
                    )
                )
                .order_by(EvaluationProfile.created_at.desc(), EvaluationProfile.id)
                .offset(offset)
                .limit(limit + 1)
            )
        )
        curves = list(
            await session.scalars(
                select(PlanningArtifact)
                .where(PlanningArtifact.kind == "throughput")
                .order_by(PlanningArtifact.created_at.desc(), PlanningArtifact.id)
                .offset(offset)
                .limit(limit + 1)
            )
        )
        has_more = any(len(rows) > limit for rows in (compilations, profiles, curves))
        compilations, profiles, curves = compilations[:limit], profiles[:limit], curves[:limit]
        source_rows = list(
            await session.scalars(
                select(StandardInputVersion).where(
                    StandardInputVersion.id.in_({c.input_id for c in compilations})
                )
            )
        )
        sources = {r.id: r.benchmark for r in source_rows}
        labels = {r.id: r.source_model + " / " + r.benchmark for r in source_rows}
        manifest_ids = {m for p in profiles for m in (p.full_manifest_id, p.lite_manifest_id) if m}
        manifests = list(
            await session.scalars(
                select(DatasetManifest).where(
                    DatasetManifest.id.in_(manifest_ids),
                    DatasetManifest.id.notin_(request.app.state.settings.archived_manifest_ids),
                )
            )
        )
        return {
            **envelope(
                {
                    "compilations": [
                        {
                            "id": str(c.id),
                            "dataset": "GPQA"
                            if sources.get(c.input_id) == "GPQA_Diamond"
                            else sources.get(c.input_id),
                            "label": labels.get(c.input_id, "")
                            + " / "
                            + c.payload.get("template_version", ""),
                            "sha256": c.sha256,
                            "adaptor_revision": c.payload.get("adaptor_revision"),
                            "runtime_config": {
                                k: v
                                for k, v in c.payload.get("runtime_config", {}).items()
                                if k not in {"work_dir", "container_name"}
                            },
                            "target_id": (c.payload.get("credential_binding") or {}).get(
                                "target_id"
                            ),
                            "config": c.payload["config"],
                            "input_ready": c.payload.get("input_ready"),
                        }
                        for c in compilations
                    ],
                    "manifests": list(
                        {
                            str(m.id): {
                                "id": str(m.id),
                                "scope": m.scope,
                                "sample_count": m.sample_count,
                                "sha256": m.sha256,
                                "dataset": p.dataset_name,
                            }
                            for p in profiles
                            for m in manifests
                            if m.id in {p.full_manifest_id, p.lite_manifest_id}
                        }.values()
                    ),
                    "curves": [
                        {
                            "id": str(c.id),
                            **{
                                k: c.payload.get(k)
                                for k in (
                                    "target_id",
                                    "resource_id",
                                    "resource_kind",
                                    "measured_at",
                                )
                            },
                        }
                        for c in curves
                    ],
                },
                request,
            ),
            "next_offset": offset + limit if has_more else None,
        }


@router.post("/throughput-profiles", status_code=201, response_model=Envelope[IdOnly])
async def import_curve(body: CurveInput, request: Request):
    from autoeval_planner.errors import PlannerError
    from autoeval_planner.throughput import ThroughputProfile

    # Request headers/body are not needed for simulation and can contain credentials.
    curve = {
        k: v
        for k, v in body.curve.items()
        if k
        in {
            "schema_version",
            "source",
            "base_url",
            "model",
            "measured_at",
            "levels",
            "derived",
            "decode_tps",
            "max_concurrency",
        }
    }
    try:
        reject_secrets(curve)
        digest(curve)  # Reject non-finite nested numbers before storing or simulating.
        profile = ThroughputProfile.from_dict(curve)
        profile.source = "manual"
    except (PlannerError, ValueError, KeyError) as exc:
        raise HTTPException(422, "Invalid throughput profile") from exc
    async with request.app.state.sessions() as session, session.begin():
        await target_data(session, body.target_id)
        row = await artifact(
            session,
            request.app.state.settings,
            "throughput",
            {
                **body.model_dump(mode="json"),
                "curve": profile.to_dict(),
                "measured_at": datetime.now(UTC).isoformat(),
                "source": "manual",
            },
        )
        return envelope({"id": str(row.id)}, request)


@router.post("/resources/preflight", status_code=202, response_model=Envelope[JobAccepted])
async def preflight(body: PlanInput | PerformanceTask, request: Request):
    async with request.app.state.sessions() as session:
        inputs = await resolve_inputs(session, request.app.state.settings, body)
    return await enqueue("preflight", inputs, request)


async def enqueue(kind, payload, request):
    async with request.app.state.sessions() as session, session.begin():
        key = request.headers.get("Idempotency-Key")
        if key:
            if len(key) > 256:
                raise HTTPException(422, "Idempotency key too long")
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "planning-job:" + key}
            )
            old = await session.scalar(
                select(PlanningJob).where(PlanningJob.payload["intent_key"].astext == key).limit(1)
            )
            if old:
                if (
                    old.kind != kind
                    or {k: v for k, v in old.payload.items() if k != "intent_key"} != payload
                ):
                    raise HTTPException(409, "Idempotency content conflict")
                return envelope(
                    {"id": str(old.id), "state": old.state, "result": old.result}, request
                )
            payload = {**payload, "intent_key": key}
        if kind == "probe":
            scope = ":".join(str(payload[k]) for k in ("target_id", "resource_kind", "resource_id"))
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": "probe-active:" + scope},
            )
            active = await session.scalar(
                select(PlanningJob.id)
                .where(
                    PlanningJob.kind == "probe",
                    PlanningJob.state.in_(["pending", "running", "unresolved"]),
                    *[
                        PlanningJob.payload[k].astext == str(payload[k])
                        for k in ("target_id", "resource_kind", "resource_id")
                    ],
                )
                .limit(1)
            )
            if active:
                raise HTTPException(
                    409,
                    f"已有探测任务 {active} 尚未结束或状态待查证，请查询或取消原任务，不能重复启动",
                )
        await artifact(session, request.app.state.settings, "job_input", payload)
        job = PlanningJob(kind=kind, payload=payload)
        session.add(job)
        await session.flush()
        return envelope({"id": str(job.id), "state": "pending"}, request)


@router.post("/probes", status_code=202, response_model=Envelope[JobAccepted])
async def probe(body: ProbeInput, request: Request):
    from autoeval.planning.probe_dispatch import consumer_ready

    async with request.app.state.sessions() as session, session.begin():
        if not await consumer_ready(session):
            raise HTTPException(503, "探测执行器未启用，未创建探测任务；请启动专用探测 Worker")
        await target_data(session, body.target_id)
    count = 2 * sum(max(n, body.requests_per_level) for n in body.concurrency)
    return await enqueue(
        "probe",
        {
            **body.model_dump(mode="json"),
            "request_budget": count,
            "max_output_token_budget": count * body.max_tokens,
        },
        request,
    )


@router.get("/active-probe", response_model=Envelope[JobStatus | None])
async def active_probe(
    target_id: uuid.UUID,
    resource_id: uuid.UUID,
    resource_kind: Literal["docker_local", "customer_ssh"],
    request: Request,
):
    async with request.app.state.sessions() as session:
        identifier = await session.scalar(
            select(PlanningJob.id)
            .where(
                PlanningJob.kind == "probe",
                PlanningJob.state.in_(["pending", "running", "unresolved"]),
                PlanningJob.payload["target_id"].astext == str(target_id),
                PlanningJob.payload["resource_id"].astext == str(resource_id),
                PlanningJob.payload["resource_kind"].astext == resource_kind,
            )
            .order_by(PlanningJob.created_at.desc())
            .limit(1)
        )
    return await job_status(identifier, request) if identifier else envelope(None, request)


@router.get("/probes/{job_id}", response_model=Envelope[JobStatus])
async def job_status(job_id: uuid.UUID, request: Request):
    async with request.app.state.sessions() as session:
        row = await session.get(PlanningJob, job_id)
        if row is None:
            raise HTTPException(404, "Planning job not found")
        result = row.result
        if row.kind == "probe" and row.state == "pending":
            from autoeval.planning.probe_dispatch import consumer_ready

            if not await consumer_ready(session, row.id, row.created_at):
                result = {
                    **(result or {}),
                    "dispatch_blocked": True,
                    "reason": "探测执行器未启用，尚未开始模型请求；请联系维护人员或取消探测",
                }
        return envelope(
            {
                "id": str(row.id),
                "kind": row.kind,
                "state": row.state,
                "result": result,
                "cancel_requested": row.cancel_requested,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            },
            request,
        )


class CloseProbe(Strict):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=5, max_length=1000)
    acknowledge_unknown: Literal[True]


@router.post("/probes/{job_id}/reconcile", response_model=Envelope[ProbeReconciled])
async def reconcile_probe(job_id: uuid.UUID, request: Request):
    from autoeval.infrastructure.contracts import JobRef
    from autoeval.planning.planning_transport import transport

    async with request.app.state.sessions() as session, session.begin():
        idle = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
            {"key": "planning:" + str(job_id)},
        )
        if not idle:
            raise HTTPException(409, "后台正在处理此探测，请稍后查询")
        row = await session.get(PlanningJob, job_id, with_for_update=True)
        if not row or row.kind != "probe":
            raise HTTPException(404, "Probe not found")
        if row.state in {"completed", "failed", "cancelled"}:
            return envelope({"id": str(row.id), "state": row.state, "result": row.result}, request)
        try:
            adapter = await transport(session, request.app.state.settings, row.payload)
            observed = await adapter.status(
                JobRef(external_job_id=str(job_id), submission_key=str(job_id))
            )
        except Exception:  # noqa: BLE001 -- do not expose remote credentials or retry generation
            raise HTTPException(503, "远程查证失败，未改变任务状态；不会重新提交模型请求") from None
        check = {
            "state": observed.state,
            "checked_at": datetime.now(UTC).isoformat(),
            "scope": "current_pinned_runtime",
        }
        result = {
            **(row.result or {}),
            "original_result": (row.result or {}).get("original_result", row.result),
            "remote_check": check,
        }
        if observed.state == "unknown":
            result["reason"] = (
                "当前固定执行环境未找到原作业；历史结果及用量未知。可由操作员确认后结束历史记录，不代表探测成功或从未调用模型。"
            )
        elif observed.state in {"failed", "cancelled"}:
            row.state = observed.state
            result["reason"] = "远程已确认探测终止；未重新提交模型请求"
        elif observed.state == "succeeded":
            result["reason"] = "远程执行已结束，结果尚需归档；不能直接视为有效吞吐曲线"
        else:
            result["reason"] = "远程作业仍存在，请等待或申请取消；不会重复提交"
        row.result = result
        return envelope(
            {
                "id": str(row.id),
                "state": row.state,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
                "result": row.result,
            },
            request,
        )


@router.post("/probes/{job_id}/close", response_model=Envelope[JobAccepted])
async def close_probe(job_id: uuid.UUID, body: CloseProbe, request: Request):
    from autoeval.infrastructure.audit import AuditEvent

    async with request.app.state.sessions() as session, session.begin():
        idle = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
            {"key": "planning:" + str(job_id)},
        )
        if not idle:
            raise HTTPException(409, "后台正在处理，不能结束记录")
        row = await session.get(PlanningJob, job_id, with_for_update=True)
        if not row or row.kind != "probe":
            raise HTTPException(404, "Probe not found")
        check = (row.result or {}).get("remote_check", {})
        if (
            row.state != "unresolved"
            or check.get("state") != "unknown"
            or datetime.fromisoformat(check["checked_at"])
            < datetime.now(UTC) - timedelta(minutes=10)
        ):
            raise HTTPException(409, "请先进行远程查证；仅允许结束最近已查证但结果仍未知的历史记录")
        before = row.result
        row.state = "failed"
        row.result = {
            **(before or {}),
            "reason": "历史探测已人工结案，执行结果及用量仍未知，不生成曲线",
            "closure": {
                "reason": body.reason,
                "closed_at": datetime.now(UTC).isoformat(),
                "execution_outcome": "unknown",
            },
        }
        session.add(
            AuditEvent(
                actor="local-operator",
                action="probe_history_closed",
                resource_type="planning_job",
                resource_id=str(row.id),
                run_id=None,
                outcome="failed",
                request_id=request.state.request_id,
                details={
                    "reason": body.reason,
                    "previous_result": before,
                    "execution_outcome": "unknown",
                },
            )
        )
        return envelope({"id": str(row.id), "state": row.state, "result": row.result}, request)


@router.post("/probes/{job_id}/cancel", status_code=202, response_model=Envelope[Accepted])
async def cancel_job(job_id: uuid.UUID, request: Request):
    async with request.app.state.sessions() as session, session.begin():
        row = await session.get(PlanningJob, job_id, with_for_update=True)
        if row is None:
            raise HTTPException(404, "Planning job not found")
        if row.state in {"pending", "running", "unresolved"}:
            row.cancel_requested = True
            if row.kind == "probe" and row.state == "pending":
                # Exclude a concurrent worker before confirming that no remote submit occurred.
                idle = await session.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                    {"key": "planning:" + str(job_id)},
                )
                if idle:
                    row.state = "cancelled"
                    row.updated_at = datetime.now(UTC)
        return envelope({"accepted": row.cancel_requested}, request)


@router.post("/plans", status_code=202, response_model=Envelope[JobAccepted])
async def plan(body: PlanInput, request: Request):
    async with request.app.state.sessions() as session:
        inputs = await resolve_inputs(session, request.app.state.settings, body)
        if not body.throughput_profile_id:
            raise HTTPException(422, "Select or probe a throughput curve before estimating")
        curve = await session.get(PlanningArtifact, body.throughput_profile_id)
        if (
            not curve
            or curve.kind != "throughput"
            or any(
                curve.payload.get(k) != inputs[k]
                for k in ("target_id", "resource_id", "resource_kind")
            )
        ):
            raise HTTPException(
                422, "Throughput curve does not match target and execution environment"
            )
    return await enqueue("plan", inputs, request)


@router.get("/plans/{job_id}", response_model=Envelope[JobStatus])
async def plan_status(job_id: uuid.UUID, request: Request):
    return await job_status(job_id, request)



@router.post("/plans/{job_id}/apply", status_code=201, response_model=Envelope[AppliedPlan])
async def apply_plan(job_id: uuid.UUID, body: ApplyInput, request: Request):
    async with request.app.state.sessions() as session, session.begin():
        job = await session.get(PlanningJob, job_id)
        if not job or job.kind != "plan" or job.state != "completed":
            raise HTTPException(409, "Plan is not ready")
        if digest(job.payload) != body.input_sha256:
            raise HTTPException(409, "Plan inputs changed")
        fresh = await current_preflight(session, job.payload)
        if not fresh or not fresh.payload.get("execution_ready"):
            raise HTTPException(409, "Fresh successful resource preflight required")
        if job.result.get("resource_sha256") != fresh.sha256:
            raise HTTPException(409, "Resource snapshot changed; replan")
        report = job.result["report"]
        inputs = copy.deepcopy(job.payload)
        try:
            from autoeval.evaluation.resource_allocation import demand_for, fits

            for item in inputs["tasks"]:
                item["concurrency"] = report["plan"]["case_concurrency"][item["task_id"]]
                item["compilation"] = apply_concurrency(item["compilation"], item["concurrency"])
                if item["dataset"] not in fresh.payload["supported_datasets"] or not fits(
                    demand_for(item), {}, fresh.payload
                ):
                    raise ValueError("Dataset or concurrency exceeds validated resource capability")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        inputs["dataset_concurrency"] = report["plan"]["dataset_concurrency"]
        inputs["tasks"].sort(key=lambda t: report["plan"]["dataset_order"].index(t["task_id"]))
        row = await artifact(
            session,
            request.app.state.settings,
            "execution",
            {
                "inputs": inputs,
                "report": report,
                "resource_sha256": fresh.sha256,
                "resource": fresh.payload,
                "source_plan_id": str(job.id),
            },
        )
        return envelope(
            {"execution_plan_id": str(row.id), "sha256": row.sha256, "report": report}, request
        )


@router.post("/runs", status_code=202, response_model=Envelope[SubmittedRun])
async def submit_run(
    body: PlanInput,
    request: Request,
    idempotency_key: str = Header(min_length=1, max_length=256),
    execution_plan_id: uuid.UUID | None = None,
):
    data = await submit_planned_run(
        request.app.state.sessions,
        request.app.state.settings,
        body,
        execution_plan_id,
        idempotency_key,
    )
    return envelope(data, request)


@router.get("/runs", response_model=PageEnvelope[PlannedRunItem])
async def list_runs(request: Request, offset: int = 0, limit: int = 20):
    from autoeval.infrastructure.models import EvaluationRun

    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid pagination")
    async with request.app.state.sessions() as session:
        rows = list(
            await session.scalars(
                select(EvaluationRun)
                .where(
                    EvaluationRun.trigger_scope == "local-operator:orchestration",
                )
                .order_by(EvaluationRun.created_at.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        )
        return {
            **envelope(
                [
                    {"id": str(r.id), "state": r.state, "created_at": r.created_at.isoformat()}
                    for r in rows[:limit]
                ],
                request,
            ),
            "next_offset": offset + limit if len(rows) > limit else None,
        }


@router.get("/runs/{run_id}", response_model=Envelope[PlannedRunDetail])
async def run_detail(run_id: uuid.UUID, request: Request):
    data = await planned_run_detail(request.app.state.sessions, run_id)
    return envelope(data, request)


@router.post("/runs/{run_id}/cancel", status_code=202, response_model=Envelope[Accepted])
async def cancel_run(run_id: uuid.UUID, request: Request):
    from autoeval.infrastructure.models import EvaluationRun

    async with request.app.state.sessions() as session, session.begin():
        run = await session.get(EvaluationRun, run_id, with_for_update=True)
        if not run or run.trigger_scope != "local-operator:orchestration":
            raise HTTPException(404, "Planned run not found")
        accepted = run.state not in {"completed", "failed", "cancelled"}
        if accepted:
            run.cancel_requested_at = datetime.now(UTC)
        return envelope({"accepted": accepted}, request)


@router.get("/runs/{run_id}/report", response_model=Envelope[dict])
async def run_report(run_id: uuid.UUID, request: Request):
    data = await planned_run_report(
        request.app.state.sessions, request.app.state.settings, run_id
    )
    return envelope(data, request)
