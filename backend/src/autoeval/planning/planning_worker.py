"""Durable planning worker: python -m autoeval.planning.planning_worker."""

import asyncio
import logging
import os
import traceback
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text

from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.db import create_database
from autoeval.infrastructure.models import RunSnapshot
from autoeval.infrastructure.secrets import FileSecretStore
from autoeval.planning.artifacts import artifact, current_preflight
from autoeval.planning.models import PlanningArtifact, PlanningJob
from autoeval.planning.planning_transport import (
    HarborDaemonUnavailable,
    execution_template,
    isolated_transport,
    transport,
)
from autoeval.planning.preflight_cache import cached_isolated_check, evidence_expires_at
from autoeval.reporting.case_history import CaseExecutionRecord
from autoeval.resources.models import TargetBinding
from autoeval.resources.targets import validate_url


class ProbePreflightBlocked(ValueError):
    """No generating submission has been attempted by this pending probe."""


async def set_job(sessions, identifier, **values):
    async with sessions() as session, session.begin():
        row = await session.get(PlanningJob, identifier, with_for_update=True)
        if values.get("state") == "completed" and row.cancel_requested:
            values["state"] = "cancelled"
        for key, value in values.items():
            if key == "result" and isinstance(value, dict):
                value = {**(row.result or {}), **value}
            setattr(row, key, value)
        row.updated_at = datetime.now(UTC)


async def preflight_isolated_task(sessions, settings, job_id, item, check, report):
    resource_id = item["assigned_resource_id"]
    frozen = item["execution_template"]
    def blocked(reason):
        return {
            "execution_ready": False,
            "planner_ready": False,
            "supported_datasets": [],
            "blocking_reasons": [reason],
            "dataset_checks": [{
                "task_id": item["task_id"],
                "dataset": item["dataset"],
                "assigned_resource_id": resource_id,
                "data_path": None,
                "tool_revision": None,
                "expected_tool_revision": item["tool"]["revision"],
                "blocking_reasons": [reason],
            }],
        }

    if execution_template(settings, resource_id, item) != frozen:
        return blocked("ssh_execution_template_changed")

    async with sessions() as session:
        adapter = await isolated_transport(
            session, settings, resource_id, uuid.uuid5(job_id, item["task_id"]), frozen
        )
    container_id = None
    try:
        await report("preparing", item)
        container_id = await adapter.ensure()
        await report("checking", item, container_id=container_id)
        result = await adapter.preflight([check])
        evidence = {
            "container_id": container_id,
            "source_job_id": str(job_id),
            "checked_at": datetime.now(UTC).isoformat(),
        }
        result["preflight_evidence"] = evidence
        for dataset_check in result["dataset_checks"]:
            dataset_check["assigned_resource_id"] = resource_id
            dataset_check["preflight_evidence"] = evidence
        return result
    except HarborDaemonUnavailable as exc:
        container_id = exc.container_id
        return blocked("harbor_private_daemon_unavailable")
    finally:
        try:
            await report("cleaning", item, container_id=container_id)
        finally:
            if not await adapter.remove():
                raise RuntimeError("Preflight container cleanup could not be confirmed")


async def execute_job(sessions, settings, identifier):
    async with sessions() as session:
        row = await session.get(PlanningJob, identifier)
        inputs, previous, kind, cancelled = row.payload, row.state, row.kind, row.cancel_requested
        if previous not in {"pending", "running"} and not (previous == "unresolved" and cancelled):
            return
        if cancelled and previous == "pending":
            await set_job(sessions, identifier, state="cancelled")
            return
        isolated_preflight = kind == "preflight" and all(
            t.get("execution_template") for t in inputs["tasks"]
        )
        prior_progress = (row.result or {}).get("preflight_progress") if isolated_preflight else None
        adapter = None if isolated_preflight else await transport(session, settings, inputs)
    if kind == "preflight" or previous != "pending":
        await set_job(sessions, identifier, state="running")
    if kind == "preflight":
        checks = [
            {key: item[key] for key in ("task_id", "dataset", "compilation", "tool")}
            for item in inputs["tasks"]
        ]
        if isolated_preflight:
            progress = {
                "assignments": {t["dataset"]: t["assigned_resource_id"] for t in inputs["tasks"]},
                "events": list((prior_progress or {}).get("events", [])),
            }

            async def report(stage, item=None, **details):
                progress["events"].append({
                    "at": datetime.now(UTC).isoformat(),
                    "stage": stage,
                    "dataset": item["dataset"] if item else None,
                    **details,
                })
                await set_job(sessions, identifier, result={"preflight_progress": progress})

            await report("resumed" if prior_progress else "started")
            task_resources = {}
            for item, check in zip(inputs["tasks"], checks, strict=True):
                try:
                    checked, reused = await cached_isolated_check(
                        sessions, settings, identifier, item, check, report, preflight_isolated_task
                    )
                except Exception:
                    await report("failed", item)
                    raise
                task_resources[item["task_id"]] = checked
                if reused:
                    await report("reused", item, **checked["preflight_evidence"])
                else:
                    await report("passed" if checked["execution_ready"] else "blocked", item)
            snapshot = {
                **next(iter(task_resources.values())),
                "task_resources": task_resources,
                "execution_templates": {t["task_id"]: t["execution_template"] for t in inputs["tasks"]},
                "dataset_checks": [c for r in task_resources.values() for c in r["dataset_checks"]],
                "supported_datasets": sorted({d for r in task_resources.values() for d in r["supported_datasets"]}),
                "execution_ready": all(r["execution_ready"] for r in task_resources.values()),
                "blocking_reasons": sorted({b for r in task_resources.values() for b in r["blocking_reasons"]}),
            }
            if snapshot["execution_ready"]:
                snapshot["preflight_valid_until"] = min(
                    evidence_expires_at(r["preflight_evidence"]) for r in task_resources.values()
                ).isoformat()
        elif inputs.get("resource_ids"):
            task_resources = {}
            for item in inputs["tasks"]:
                async with sessions() as session:
                    assigned = {**inputs, "resource_id": item["assigned_resource_id"], "resource_kind": item["assigned_resource_kind"]}
                    selected_adapter = await transport(session, settings, assigned)
                task_resources[item["task_id"]] = await selected_adapter.preflight([next(c for c in checks if c["task_id"] == item["task_id"])])
            first = next(iter(task_resources.values()))
            snapshot = {**first, "task_resources": task_resources, "dataset_checks": [c for r in task_resources.values() for c in r["dataset_checks"]], "supported_datasets": sorted({d for r in task_resources.values() for d in r["supported_datasets"]}), "execution_ready": all(r["execution_ready"] for r in task_resources.values()), "blocking_reasons": sorted({b for r in task_resources.values() for b in r["blocking_reasons"]})}
        else:
            snapshot = await adapter.preflight(checks)
        async with sessions() as session, session.begin():
            saved = await artifact(session, settings, "resource", {**inputs, **snapshot})
            result = {"resource_snapshot_id": str(saved.id), **saved.payload}
        await set_job(sessions, identifier, state="completed", result=result)
        return
    if kind == "plan":
        async with sessions() as session:
            curve = await session.get(PlanningArtifact, inputs["throughput_profile_id"])
            snapshot = await current_preflight(session, inputs)
            if previous == "pending" and (not snapshot or not snapshot.payload.get("planner_ready")):
                await set_job(
                    sessions,
                    identifier,
                    state="failed",
                    result={
                        "error_code": "plan_preflight_required",
                        "reason": "当前配置缺少有效的规划预检，请重新检查环境后估算。",
                    },
                )
                return
            observations = (
                await session.execute(
                    select(CaseExecutionRecord, RunSnapshot)
                    .join(
                        RunSnapshot,
                        RunSnapshot.run_id == CaseExecutionRecord.run_id,
                    )
                    .where(
                        CaseExecutionRecord.dataset_key.in_(
                            [t["dataset"] for t in inputs["tasks"]]
                        ),
                        CaseExecutionRecord.finished_at.is_not(None),
                        CaseExecutionRecord.state != "started",
                    )
                )
            ).all()
            history = [
                {
                    "run_id": str(c.run_id),
                    "dataset": c.dataset_key,
                    "sample_id": c.sample_id,
                    "attempt": c.attempt_no,
                    "state": c.state,
                    "metadata": c.tool_metadata or {},
                    "finished_at": c.finished_at.isoformat(),
                }
                for c, s in observations
                if s.canonical_body.get("execution_origin") == "real"
            ]
            resource = snapshot.payload if snapshot else None
            resource_sha = snapshot.sha256 if snapshot else None
            profile = curve.payload["curve"]
        if not snapshot or not snapshot.payload.get("planner_ready"):
            raise ValueError("Fresh pinned container preflight required")
        key = str(identifier)
        if previous == "pending":
            await set_job(sessions, identifier, state="running")
            job = await adapter.submit(
                {
                    "kind": "planner_plan",
                    "credential": "",
                    "inputs": inputs,
                    "curve": profile,
                    "resource": resource,
                    "history": history,
                },
                key,
            )
        else:
            from autoeval.infrastructure.contracts import JobRef

            job = JobRef(external_job_id=key, submission_key=key)
        while True:
            async with sessions() as session:
                cancelled = (await session.get(PlanningJob, identifier)).cancel_requested
            observed = (
                await adapter.cancel(job, "cancel:" + key)
                if cancelled
                else await adapter.status(job)
            )
            if observed.state in {"unknown", "cleaned"}:
                await set_job(
                    sessions,
                    identifier,
                    state="unresolved",
                    result={"reason": "remote_plan_unknown"},
                )
                return
            if observed.state in {"succeeded", "failed", "cancelled"}:
                break
            await asyncio.sleep(2)
        if observed.state != "succeeded" or cancelled:
            await set_job(
                sessions,
                identifier,
                state="cancelled" if cancelled else "failed",
                result={"reason": observed.reason or "remote_plan_failed"},
            )
            await adapter.cleanup(job)
            return
        collected = await adapter.collect(job)
        report = collected["result"]["report"]
        async with sessions() as session, session.begin():
            saved = await artifact(session, settings, "plan", {"inputs": inputs, "report": report})
        await set_job(
            sessions,
            identifier,
            state="completed",
            result={
                "artifact_id": str(saved.id),
                "report": report,
                "resource_sha256": resource_sha,
            },
        )
        await adapter.cleanup(job)
        return
    # Remote probe submission is never automatically repeated after an uncertain response.
    async with sessions() as session:
        snapshot = await current_preflight(
            session, inputs, probe_container=[getattr(adapter, "container_id", None), getattr(adapter, "image_id", None)]
        )
        if previous == "pending":
            # Selection preflight may expire while users review budgets. Refresh read-only
            # environment evidence here; never let a stale check imply a model was called.
            resource = snapshot.payload if snapshot else None
            if not resource or not resource.get("planner_ready"):
                try:
                    resource = await adapter.preflight()
                except Exception as exc:
                    frames = traceback.extract_tb(exc.__traceback__)
                    logging.getLogger(__name__).warning(
                        "Probe preflight blocked job=%s type=%s stages=%s",
                        identifier, type(exc).__name__, [frame.name for frame in frames],
                    )
                    raise ProbePreflightBlocked(
                        "探测前环境检查失败，未提交模型请求，请检查执行资源后重试"
                    ) from exc
            if not resource.get("planner_ready"):
                raise ProbePreflightBlocked("探测组件版本未就绪，未提交模型请求")
            maximum = resource.get("max_probe_concurrency")
            if not isinstance(maximum, int) or max(inputs["concurrency"]) > maximum:
                raise ProbePreflightBlocked("探测并发超过资源允许范围，未提交模型请求")
        target = await session.get(TargetBinding, inputs["target_id"])
        validate_url(target.base_url, settings.allowed_model_hosts)
        spec = {
            "kind": "planner_probe",
            "credential": FileSecretStore(settings.secret_store_path).get(target.credential_ref),
            "options": {
                "base_url": target.base_url,
                "model": target.remote_model,
                "concurrency_levels": inputs["concurrency"],
                **{k: inputs[k] for k in ("requests_per_level", "prompt_tokens", "max_tokens")},
            },
        }
    key = str(identifier)
    if previous == "pending":
        async with sessions() as session:
            cancelled = (await session.get(PlanningJob, identifier)).cancel_requested
        if cancelled:
            await set_job(sessions, identifier, state="cancelled")
            return
        await set_job(sessions, identifier, state="running")
        job = await adapter.submit(spec, key)
    else:
        from autoeval.infrastructure.contracts import JobRef

        job = JobRef(external_job_id=key, submission_key=key)
    while True:
        async with sessions() as session:
            cancelled = (await session.get(PlanningJob, identifier)).cancel_requested
        observation = (
            await adapter.cancel(job, "cancel:" + key) if cancelled else await adapter.status(job)
        )
        try:
            progress = await adapter.progress(job)
            if progress:
                await set_job(sessions, identifier, result={"progress": progress})
        except Exception:  # noqa: BLE001, S110 -- monitoring failure must not restart model requests
            pass
        if observation.state in {"succeeded", "failed", "cancelled"}:
            break
        if observation.state in {"unknown", "cleaned"}:
            await set_job(
                sessions,
                identifier,
                state="unresolved",
                result={
                    "reason": "Remote submission uncertain; no generation request was repeated"
                },
            )
            return
        await asyncio.sleep(2)
    if observation.state == "succeeded" and not cancelled:
        result = await adapter.collect(job)
        async with sessions() as session, session.begin():
            saved = await artifact(
                session,
                settings,
                "throughput",
                {
                    **{k: inputs[k] for k in ("target_id", "resource_id", "resource_kind")},
                    "curve": result["result"]["curve"],
                    "source": "probe",
                    "measured_at": datetime.now(UTC).isoformat(),
                },
            )
        await set_job(
            sessions,
            identifier,
            state="completed",
            result={
                "throughput_profile_id": str(saved.id),
                "progress": result["result"].get("progress"),
            },
        )
    else:
        await set_job(
            sessions,
            identifier,
            state="cancelled" if cancelled else "failed",
            result={
                "reason": "probe_cancelled"
                if cancelled
                else observation.reason or "remote_probe_failed"
            },
        )
    await adapter.cleanup(job)


async def serve():
    settings = get_settings()
    engine, sessions = create_database(settings)
    probe_ids = [
        uuid.UUID(v.strip())
        for v in os.environ.get("AE_PLANNING_PROBE_JOB_IDS", "").split(",")
        if v.strip()
    ]
    kinds = os.environ.get("AE_PLANNING_JOB_KINDS", "preflight,plan").split(",")
    cutoff_value = os.environ.get("AE_PLANNING_PROBE_ACCEPT_AFTER")
    cutoff = datetime.fromisoformat(cutoff_value) if cutoff_value else None
    if cutoff is not None and cutoff.tzinfo is None:
        raise ValueError("Probe cutoff must include timezone")
    consumer = None
    if "probe" in kinds:
        from autoeval.planning.probe_dispatch import consumer_key

        consumer = await engine.connect()
        for key in (
            [consumer_key(v) for v in probe_ids] if probe_ids and not cutoff else [consumer_key()]
        ):
            await consumer.execute(
                text("SELECT pg_advisory_lock_shared(hashtext(:key))"), {"key": key}
            )
        if cutoff:
            await consumer.execute(
                text("SELECT pg_advisory_lock_shared(1095062608, :cutoff)"),
                {"cutoff": int(cutoff.timestamp())},
            )
        await consumer.commit()
    try:
        while True:
            async with sessions() as session:
                ids = list(
                    await session.scalars(
                        select(PlanningJob.id)
                        .where(
                            (
                                PlanningJob.kind.in_(
                                    os.environ.get("AE_PLANNING_JOB_KINDS", "preflight,plan").split(
                                        ","
                                    )
                                )
                                & PlanningJob.state.in_(["pending", "running"])
                                | (
                                    (PlanningJob.state == "unresolved")
                                    & PlanningJob.cancel_requested.is_(True)
                                )
                            ),
                        )
                        .where(
                            (PlanningJob.kind != "probe")
                            | (
                                PlanningJob.id.in_(probe_ids)
                                | (PlanningJob.created_at >= cutoff if cutoff else False)
                            )
                            if probe_ids or cutoff
                            else True
                        )
                        .where(PlanningJob.kind.in_(kinds))
                        .order_by(PlanningJob.created_at)
                        .limit(20)
                    )
                )
            for identifier in ids:
                # Session-level lock survives commits and is released if this worker dies.
                async with engine.connect() as connection:
                    lock = "planning:" + str(identifier)
                    owned = await connection.scalar(
                        text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": lock}
                    )
                    if not owned:
                        continue
                    try:
                        await execute_job(sessions, settings, identifier)
                    except Exception as exc:  # noqa: BLE001 -- isolate third-party errors without leaking credentials
                        # Do not log exception messages or locals: third-party errors may contain keys.
                        logging.getLogger(__name__).error(
                            "Planning job failed job=%s exception_type=%s frames=%s",
                            identifier,
                            type(exc).__name__,
                            [
                                (
                                    PathFrame.filename.rsplit("/", 1)[-1],
                                    PathFrame.lineno,
                                    PathFrame.name,
                                )
                                for PathFrame in traceback.extract_tb(exc.__traceback__)
                            ],
                        )
                        async with sessions() as session:
                            failed = await session.get(PlanningJob, identifier)
                            uncertain = (
                                failed.kind in {"probe", "plan"}
                                and failed.state == "running"
                                and not isinstance(exc, ProbePreflightBlocked)
                            )
                        await set_job(
                            sessions,
                            identifier,
                            state="unresolved" if uncertain else "failed",
                            result={
                                "reason": str(exc)
                                if isinstance(exc, ProbePreflightBlocked)
                                else "操作失败，请检查执行资源与工具版本；未确认提交结果前不会自动重试",
                                "error_code": "probe_preflight_blocked"
                                if isinstance(exc, ProbePreflightBlocked)
                                else "planning_operation_failed",
                                "exception_type": type(exc).__name__,
                            },
                        )
                    finally:
                        await connection.execute(
                            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": lock}
                        )
            await asyncio.sleep(settings.poll_seconds)
    finally:
        if consumer is not None:
            await consumer.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(serve())
