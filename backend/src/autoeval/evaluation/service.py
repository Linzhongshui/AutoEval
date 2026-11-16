"""Evaluation application services: input resolution, preflight, submission and queries.

The service layer owns transactions and receives explicit dependencies
(session factory, settings, operator parameters) instead of FastAPI requests.
Business errors keep raising HTTPException; the global exception handlers in
``autoeval.api`` convert them to the existing error envelope unchanged.
"""

import asyncio
import copy
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, text

from autoeval.datasets import DatasetManifest, canonical_manifest, read_manifest, write_manifest
from autoeval.evaluation.models import CapacityLease, DatasetExecution
from autoeval.infrastructure.domain import RUN_TERMINAL
from autoeval.models import EvaluationRun, Outbox, RunEvent, RunSnapshot
from autoeval.planning_engine import PLANNER_REVISION, apply_concurrency, selected_samples
from autoeval.standard_inputs import (
    StandardInputCompilation,
    StandardInputVersion,
    digest,
    leaves,
)
from autoeval.targets import TargetBinding, validate_url


async def artifact(session, settings, kind, payload):
    # Deferred: autoeval.planning re-exports this module, so its ORM models are
    # imported lazily to keep module loading acyclic.
    from autoeval.planning.models import PlanningArtifact

    raw = canonical_manifest(payload)
    sha = digest(payload)
    key = f"planning/{kind}/{sha}.json"
    await asyncio.to_thread(write_manifest, settings, key, raw)
    row = PlanningArtifact(kind=kind, sha256=sha, object_key=key, payload=payload)
    session.add(row)
    await session.flush()
    return row


async def target_data(session, target_id):
    target = await session.get(TargetBinding, target_id)
    if target is None:
        raise HTTPException(404, "Target not found")
    return {"base_url": target.base_url, "model": target.remote_model}


def manifest_dataset_matches(dataset, asset_key):
    aliases = {"GPQA": {"GPQA", "GPQA_Diamond", "gpqa-diamond"}}
    return asset_key in aliases.get(dataset, {dataset})


async def resolve_inputs(session, settings, body):
    from autoeval.profiles import EvaluationProfile
    from autoeval.registry import Asset, AssetVersion

    target = await target_data(session, body.target_id)
    tasks = []
    for spec in body.tasks:
        if spec.manifest_id in settings.archived_manifest_ids:
            raise HTTPException(409, "该样本清单已归档，请重新选择可用清单")
        compilation = await session.get(StandardInputCompilation, spec.compilation_id)
        manifest = await session.get(DatasetManifest, spec.manifest_id)
        if not compilation or not manifest:
            raise HTTPException(404, "Compilation or manifest not found")
        version = await session.get(AssetVersion, manifest.dataset_version_id)
        asset_row = await session.get(Asset, version.asset_id)
        if not manifest_dataset_matches(spec.dataset, asset_row.asset_key):
            raise HTTPException(422, "Manifest dataset identity mismatch")
        profile = await session.scalar(
            select(EvaluationProfile)
            .where(
                EvaluationProfile.dataset_name == spec.dataset,
                (EvaluationProfile.full_manifest_id == manifest.id)
                | (EvaluationProfile.lite_manifest_id == manifest.id),
            )
            .order_by(EvaluationProfile.created_at.desc())
            .limit(1)
        )
        if not profile:
            raise HTTPException(422, "Versioned tool/scorer profile required for selected manifest")
        compiled = copy.deepcopy(compilation.payload)
        if (
            not compiled.get("input_ready")
            or compiled.get("adaptor_revision") != "955089ab32ef696c231d628f5ad0d9da28f430c4"
        ):
            raise HTTPException(422, "Compilation is blocked or uses an unsupported adaptor")
        if (compiled.get("credential_binding") or {}).get("target_id") != str(body.target_id):
            raise HTTPException(422, "Compilation belongs to another target")
        source_input = await session.get(StandardInputVersion, compilation.input_id)
        if source_input.benchmark != ("GPQA_Diamond" if spec.dataset == "GPQA" else spec.dataset):
            raise HTTPException(422, "Compilation dataset identity mismatch")
        if spec.concurrency is not None:
            try:
                compiled = apply_concurrency(compiled, spec.concurrency)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        config = compiled["config"]
        params = config["params"]
        if config["subcommand"] == "llm_accuracy":
            if params.get("dump_eval_details") is False:
                raise HTTPException(
                    422, "Per-case scoring details are required for report evidence"
                )
            params["dump_eval_details"] = True
        if config["subcommand"] == "llm_accuracy" and len(params.get("datasets", [])) != 1:
            raise HTTPException(422, "Each compilation must select exactly one dataset")
        if (spec.dataset in {"DeepSWE", "AutomationBench"}) != (
            config["subcommand"] == "harbor_agent"
        ):
            raise HTTPException(422, "Dataset tool family mismatch")
        full = await session.get(DatasetManifest, profile.full_manifest_id)
        source = await asyncio.to_thread(read_manifest, settings, full)
        samples = [
            dict(
                sample,
                tool_case_id=str(i)
                if spec.dataset not in {"DeepSWE", "AutomationBench"}
                else sample["sample_id"],
            )
            for i, sample in enumerate(source["samples"])
        ]
        if manifest.scope == "lite":
            lite = await asyncio.to_thread(read_manifest, settings, manifest)
            wanted = {s["sample_id"]: s["sha256"] for s in lite["samples"]}
            if any(
                wanted.get(s["sample_id"]) != s["sha256"]
                for s in samples
                if s["sample_id"] in wanted
            ):
                raise HTTPException(422, "Lite manifest differs from full manifest")
            # Accuracy Lite selections must map to a contiguous tool range.
            positions = [i for i, s in enumerate(samples) if s["sample_id"] in wanted]
            if len(positions) != len(wanted):
                raise HTTPException(422, "Lite samples missing from full manifest")
            if config["subcommand"] == "llm_accuracy":
                if positions != list(range(positions[0], positions[-1] + 1)):
                    raise HTTPException(
                        422,
                        "Non-contiguous accuracy Lite selection is not supported by this adaptor",
                    )
                params["dataset_test_range"] = f"[{positions[0]}:{positions[-1] + 1}]"
            else:
                params["task_names"] = list(wanted)
        chosen = selected_samples(config, samples)
        if config["subcommand"] == "llm_accuracy":
            # AISBench dataset slicing is authoritative; num_prompts is not consistently
            # honored across supported versions. Freeze the exact effective tool range.
            params["dataset_test_range"] = (
                f"[{chosen[0]['tool_case_id']}:{int(chosen[-1]['tool_case_id']) + 1}]"
            )
        field = "batch_size" if config["subcommand"] == "llm_accuracy" else "n_concurrent_trials"
        attempts = (
            int(params.get("n_attempts", 1))
            if spec.dataset in {"DeepSWE", "AutomationBench"}
            else 1
        )
        concurrency = int(params.get(field, 1))
        if not 1 <= concurrency <= 256 or not 1 <= attempts <= 100:
            raise HTTPException(422, "Invalid concurrency or attempts")
        tasks.append(
            {
                **spec.model_dump(mode="json"),
                "compilation": compiled,
                "compilation_sha256": compilation.sha256,
                "manifest_sha256": manifest.sha256,
                "profile_sha256": profile.sha256,
                "tool": profile.contract,
                "samples": chosen,
                "dataset_samples": full.sample_count,
                "subset_scope": manifest.scope,
                "attempts": attempts,
                "concurrency": concurrency,
            }
        )
    return {
        **body.model_dump(mode="json"),
        "target": target,
        "tasks": tasks,
        "planner_revision": PLANNER_REVISION,
    }


def selection_identity(inputs):
    return sorted(
        (
            {
                **{
                    key: task[key]
                    for key in ("task_id", "dataset", "compilation_id", "manifest_id")
                },
                "profile_sha256": task.get("profile_sha256"),
                "concurrency": task.get("concurrency"),
            }
            for task in inputs.get("tasks", [])
        ),
        key=lambda task: task["task_id"],
    )


async def current_preflight(session, inputs, *, require_selection=True):
    from autoeval.planning.models import PlanningArtifact

    rows = (
        await session.scalars(
            select(PlanningArtifact)
            .where(PlanningArtifact.kind == "resource")
            .order_by(PlanningArtifact.created_at.desc())
            .limit(100)
        )
    ).all()
    return next(
        (
            r
            for r in rows
            if all(r.payload.get(k) == inputs[k] for k in ("resource_id", "resource_kind"))
            and (
                not require_selection
                or (
                    r.payload.get("target_id") == inputs.get("target_id")
                    and selection_identity(r.payload) == selection_identity(inputs)
                )
            )
            and r.created_at > datetime.now(UTC) - timedelta(minutes=5)
        ),
        None,
    )


def demand_for(item):
    count = item["concurrency"]
    params = item["compilation"]["config"]["params"]
    if item["dataset"] == "DeepSWE":
        return {
            "cpu": 0.5 + count * max(2, float(params.get("override_cpus") or 2)),
            "mem": 256 + count * max(8192, int(params.get("override_memory_mb") or 8192)),
            "disk": count * max(20, float(params.get("override_storage_mb") or 20480) / 1024),
            "networks": count,
        }
    return {"cpu": 1 + count * 0.02, "mem": 1024 + count * 16, "disk": 0, "networks": 0}


def fits(demand, used, resource):
    limits = {
        "cpu": resource["cpu_cores"] * 0.8,
        "mem": resource["mem_mb"] * 0.8,
        "disk": resource["disk_gb"] * 0.8,
        "networks": resource.get("network_available") or 0,
    }
    return all(demand[k] + used.get(k, 0) <= limits[k] for k in limits)


async def acquire(session, owner, resource, demand):
    node = resource["node_id"]
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "capacity:" + node}
    )
    existing = await session.scalar(select(CapacityLease).where(CapacityLease.owner_id == owner))
    if existing:
        return not existing.released
    leases = (
        await session.scalars(
            select(CapacityLease).where(
                CapacityLease.node_id == node,
                CapacityLease.released.is_(False),
            )
        )
    ).all()
    used = {k: sum(row.demand.get(k, 0) for row in leases) for k in demand}
    if not fits(demand, used, resource):
        return False
    session.add(CapacityLease(owner_id=owner, node_id=node, demand=demand))
    return True


async def release(session, owner):
    lease = await session.scalar(select(CapacityLease).where(CapacityLease.owner_id == owner))
    if lease:
        lease.released = True


async def create_run(session, settings, body, execution_plan_id, key):
    from autoeval.planning.models import PlanningArtifact, PlanningJob

    if not execution_plan_id:
        body = body.model_copy(update={"recommend": False, "throughput_profile_id": None})
    request_hash = digest(
        {
            "request": body.model_dump(mode="json"),
            "execution_plan_id": str(execution_plan_id) if execution_plan_id else None,
        }
    )
    old = await session.scalar(
        select(EvaluationRun).where(
            EvaluationRun.trigger_scope == "local-operator:orchestration",
            EvaluationRun.idempotency_key == key,
        )
    )
    if old:
        if old.request_hash != request_hash:
            raise HTTPException(409, "Idempotency content conflict")
        return {"run_id": str(old.id), "state": old.state}
    if settings.evaluation_origin != "real":
        raise HTTPException(
            409, "General model execution requires an explicit real execution origin"
        )
    inputs = await resolve_inputs(session, settings, body)
    fresh = await current_preflight(session, inputs)
    if not fresh or not fresh.payload.get("execution_ready"):
        raise HTTPException(409, "Fresh resource preflight required")
    report = None
    if execution_plan_id:
        execution = await session.get(PlanningArtifact, execution_plan_id)
        if not execution or execution.kind != "execution":
            raise HTTPException(404, "Execution plan missing")
        original = await session.get(PlanningJob, execution.payload["source_plan_id"])
        if {k: v for k, v in original.payload.items() if k != "intent_key"} != inputs:
            raise HTTPException(409, "Selected inputs changed; regenerate plan")
        if execution.payload["resource_sha256"] != fresh.sha256:
            raise HTTPException(409, "Resource snapshot changed; regenerate plan")
        inputs = copy.deepcopy(execution.payload["inputs"])
        report = execution.payload["report"]
    else:
        # Direct execution freezes the supplied settings without optimizer rewrites.
        inputs = copy.deepcopy(inputs)
        for item in inputs["tasks"]:
            if int(item["compilation"]["config"]["params"].get("max_num_workers", 1)) != 1:
                raise HTTPException(
                    409, "Platform owns dataset parallelism; configure max_num_workers=1"
                )
    for item in inputs["tasks"]:
        if item["dataset"] not in fresh.payload["supported_datasets"] or not fits(
            demand_for(item), {}, fresh.payload
        ):
            raise HTTPException(
                409, "Selected dataset/concurrency exceeds execution resource capability"
            )
        compiled = item["compilation"]
        if any(
            leaves(compiled["config"]).get(k) != v
            for k, v in compiled.get("locked_fields", {}).items()
        ):
            raise HTTPException(409, "Selected sample range conflicts with standard locks")
    target = await session.get(TargetBinding, body.target_id)
    validate_url(target.base_url, settings.allowed_model_hosts)
    run = EvaluationRun(
        trigger_scope="local-operator:orchestration",
        idempotency_key=key,
        request_hash=request_hash,
        run_mode="exploration",
        created_by="local-operator",
    )
    session.add(run)
    await session.flush()
    frozen = {
        "schema_version": "planned-run.v1",
        "inputs": inputs,
        "estimate": report,
        "execution_mode": "optimized" if execution_plan_id else "direct",
        "resource": fresh.payload,
        "resource_sha256": fresh.sha256,
        "target_id": str(target.id),
        "resource_id": inputs["resource_id"],
        "resource_kind": inputs["resource_kind"],
        "remote_model": target.remote_model,
        "execution_origin": settings.evaluation_origin,
    }
    # A single GPQA result can use the existing report/leaderboard contract without
    # changing its frozen planning inputs or inventing aggregate multi-dataset scores.
    if len(inputs["tasks"]) == 1 and inputs["tasks"][0]["dataset"] == "GPQA":
        task = inputs["tasks"][0]
        params = task["compilation"]["config"]["params"]
        generation = params.get("generation_kwargs", {})
        frozen.update(
            {
                "dataset_key": "GPQA",
                "manifest_id": task["manifest_id"],
                "manifest_sha256": task["manifest_sha256"],
                "tool": task["tool"],
                "config_version_id": task["compilation_id"],
                "parameters": {
                    "scope": task.get("subset_scope", "lite"),
                    "output": params.get("max_out_len"),
                    "concurrency": task["concurrency"],
                    "temperature": generation.get("temperature"),
                    "top_p": generation.get("top_p"),
                },
            }
        )
    session.add(
        RunSnapshot(
            run_id=run.id,
            schema_version="planned-run.v1",
            canonical_body=frozen,
            sha256=digest(frozen),
        )
    )
    from autoeval.task_monitor import MonitorBinding

    for index, item in enumerate(inputs["tasks"], 1):
        child_id = uuid.uuid4()
        session.add(
            DatasetExecution(id=child_id, run_id=run.id, task_id=item["task_id"], payload=item)
        )
        session.add(
            MonitorBinding(
                run_id=run.id,
                attempt=index,
                identity={
                    "task_name": str(child_id),
                    "dataset": item["dataset"],
                    "child_id": str(child_id),
                },
            )
        )
    session.add(
        Outbox(
            run_id=run.id,
            kind="START_RUN",
            dedup_key="planned:" + str(run.id),
            payload={"workflow_kind": "planned_evaluation"},
        )
    )
    return {"run_id": str(run.id), "state": "accepted"}


async def submit_planned_run(sessions, settings, body, execution_plan_id, key):
    """Submit an orchestrated evaluation run inside one transaction."""
    async with sessions() as session, session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": "orchestration:" + key},
        )
        return await create_run(session, settings, body, execution_plan_id, key)


async def planned_run_detail(sessions, run_id):
    """Read one planned run with children and the archived report reference."""
    from autoeval.evaluation.models import EvaluationReport
    from autoeval.planning.models import PlanningArtifact

    async with sessions() as session:
        run = await session.get(EvaluationRun, run_id)
        if not run or run.trigger_scope != "local-operator:orchestration":
            raise HTTPException(404, "Planned run not found")
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        children = list(
            await session.scalars(select(DatasetExecution).where(DatasetExecution.run_id == run_id))
        )
        reports = list(
            await session.scalars(
                select(PlanningArtifact)
                .where(
                    PlanningArtifact.kind == "run_report",
                    PlanningArtifact.payload["run_id"].astext == str(run_id),
                )
                .limit(1)
            )
        )
        report_id = await session.scalar(
            select(EvaluationReport.id).where(EvaluationReport.run_id == run_id)
        )
        from autoeval.evaluation.orchestration import child_view

        return {
            "report_id": str(report_id) if report_id else None,
            "id": str(run.id),
            "state": run.state,
            "estimate": snapshot.canonical_body.get("estimate"),
            "datasets": [child_view(c) for c in children],
            "report": reports[0].payload if reports else None,
            "execution_origin": snapshot.canonical_body.get("execution_origin"),
        }


async def planned_run_report(sessions, settings, run_id):
    """Read the archived planned-run report evidence."""
    from autoeval.planning.models import PlanningArtifact

    async with sessions() as session:
        report = await session.scalar(
            select(PlanningArtifact)
            .where(
                PlanningArtifact.kind == "run_report",
                PlanningArtifact.payload["run_id"].astext == str(run_id),
            )
            .limit(1)
        )
        if report is None:
            raise HTTPException(404, "Report not available")
        try:
            return await asyncio.to_thread(read_manifest, settings, report)
        except ValueError as exc:
            raise HTTPException(503, "Report evidence integrity check failed") from exc


async def evaluation_run_detail(sessions, settings, run_id):
    """Read one evaluation run with events, snapshot, report and cleanup state."""
    from sqlalchemy.exc import SQLAlchemyError

    from autoeval.cleanup import ExecutionCleanup, cleanup_view
    from autoeval.evaluation.models import EvaluationReport

    try:
        async with sessions() as session:
            row = await session.get(EvaluationRun, run_id)
            if row is None or row.trigger_scope not in {
                "local-operator:evaluation",
                "local-operator:orchestration",
            }:
                raise HTTPException(404, "Evaluation run not found")
            events = (
                await session.scalars(
                    select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
                )
            ).all()
            report = await session.scalar(
                select(EvaluationReport).where(EvaluationReport.run_id == run_id)
            )
            cleanup = await session.scalar(
                select(ExecutionCleanup).where(ExecutionCleanup.run_id == run_id)
            )
            snapshot = await session.scalar(
                select(RunSnapshot).where(RunSnapshot.run_id == run_id)
            )
            return {
                "id": str(row.id),
                "state": row.state,
                "created_at": row.created_at.isoformat(),
                "updated_at": events[-1].created_at.isoformat()
                if events
                else row.created_at.isoformat(),
                "cancel_requested_at": row.cancel_requested_at.isoformat()
                if row.cancel_requested_at
                else None,
                "run_mode": row.run_mode,
                "snapshot": {
                    "sha256": snapshot.sha256,
                    **{
                        key: snapshot.canonical_body.get(key)
                        for key in (
                            "config_version_id",
                            "config_sha256",
                            "parameters",
                            "tool",
                            "profile_id",
                            "profile_sha256",
                            "max_model_requests",
                            "target_id",
                            "model_version_id",
                            "remote_model",
                            "resource_id",
                            "resource_kind",
                            "manifest_id",
                            "manifest_sha256",
                            "execution_origin",
                        )
                    },
                    # Planned runs freeze per-dataset samples instead of a top-level list.
                    "sample_count": len(snapshot.canonical_body.get("samples", []))
                    if snapshot.canonical_body.get("samples") is not None
                    else sum(
                        len(task.get("samples") or [])
                        for task in (snapshot.canonical_body.get("inputs") or {}).get(
                            "tasks", []
                        )
                    ),
                }
                if snapshot
                else None,
                "gate_status": "not_applicable",
                "cleanup": cleanup_view(
                    cleanup,
                    required=bool(
                        snapshot
                        and snapshot.canonical_body.get("resource_kind") == "customer_ssh"
                        and row.trigger_scope == "local-operator:evaluation"
                    ),
                ),
                "execution_unresolved": bool(
                    events and events[-1].type == "execution_unresolved"
                ),
                "events": [
                    {"seq": e.seq, "type": e.type, "created_at": e.created_at.isoformat()}
                    for e in events
                ],
                "report": {
                    "id": str(report.id),
                    "validity": report.validity,
                    "summary": report.summary,
                    "sha256": report.sha256,
                }
                if report
                else None,
            }
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Run database unavailable") from exc


async def evaluation_run_report(sessions, settings, run_id):
    """Read the archived evaluation report evidence from object storage."""
    from botocore.exceptions import BotoCoreError, ClientError
    from sqlalchemy.exc import SQLAlchemyError

    from autoeval.evaluation.models import EvaluationReport

    try:
        async with sessions() as session:
            report = await session.scalar(
                select(EvaluationReport).where(EvaluationReport.run_id == run_id)
            )
            if report is None:
                raise HTTPException(404, "Report not available")
            return await asyncio.to_thread(read_manifest, settings, report)
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Report database unavailable") from exc
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise HTTPException(
            503, "Report evidence unavailable or integrity check failed"
        ) from exc


async def evaluation_retry_cleanup(sessions, settings, run_id):
    """Schedule resource reclamation for a terminal SSH run from this origin."""
    from autoeval.cleanup import schedule_cleanup

    async with sessions() as session, session.begin():
        row = await session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update()
        )
        snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
        if row is None or row.trigger_scope != "local-operator:evaluation":
            raise HTTPException(404, "Evaluation run not found")
        if (
            row.state not in RUN_TERMINAL
            or snapshot is None
            or snapshot.canonical_body.get("resource_kind") != "customer_ssh"
            or snapshot.canonical_body.get("execution_origin") != settings.evaluation_origin
        ):
            raise HTTPException(
                409, "Only terminal SSH runs from this execution origin may be reclaimed"
            )
        cleanup = await schedule_cleanup(session, run_id)
        if cleanup.state != "cleaned":
            cleanup.next_retry_at = None
        return {"accepted": True}
