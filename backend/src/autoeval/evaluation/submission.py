import copy
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, text

from autoeval.evaluation.inputs import resolve_inputs
from autoeval.evaluation.models import DatasetExecution
from autoeval.evaluation.resource_allocation import (
    demand_for,
    fits,
    resource_for_task,
)
from autoeval.models import EvaluationRun, Outbox, RunSnapshot
from autoeval.planning.artifacts import current_preflight
from autoeval.standard_inputs import (
    digest,
    leaves,
)
from autoeval.targets import TargetBinding, validate_url


async def create_run(session, settings, body, execution_plan_id, key):
    from autoeval.planning.models import PlanningArtifact, PlanningJob

    if not getattr(settings, "enforce_task_budget", False):
        body = body.model_copy(update={"ignore_budget": True})
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
            demand_for(item), {}, resource_for_task(fresh.payload, item["task_id"])
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
    budget_config_path = getattr(settings, 'billing_execution_config', None)
    if body.ignore_budget:
        acknowledged_at = datetime.now(UTC)
        frozen['model_budget'] = {
            'mode': 'ignored', 'acknowledged_by': run.created_by,
            'acknowledged_at': acknowledged_at.isoformat(),
            'execution_deadline': (acknowledged_at + timedelta(hours=24)).isoformat(),
        }
    elif budget_config_path:
        import json
        from pathlib import Path

        budget_config = json.loads(Path(budget_config_path).read_text())
        from autoeval.billing import BudgetAccount
        from autoeval.billing_transport import execution_route, route_compilation

        expected = budget_config.get('expected_scope')
        if expected and ({t['dataset']: len(t.get('samples', [])) for t in inputs['tasks']} != expected
                         or any(t.get('concurrency') != 24 or t.get('subset_scope') != 'full'
                                for t in inputs['tasks'])):
            raise HTTPException(422, '当前预算仅适用于已授权的全量测评；其他范围可勾选“忽略本次任务预算限制”')
        if datetime.now(UTC) >= datetime.fromisoformat(budget_config['deadline']):
            raise HTTPException(409, '当前预算已过期，请配置新预算或勾选“忽略本次任务预算限制”')
        account = await session.scalar(select(BudgetAccount).where(
            BudgetAccount.id == uuid.UUID(budget_config['budget_id'])).with_for_update())
        if account is None or account.state != 'active' or not account.policy.get('enforcement_ready'):
            raise HTTPException(409, '当前预算限制未就绪，请检查配置或勾选“忽略本次任务预算限制”')
        if account.policy.get('run_id') not in (None, str(run.id)):
            raise HTTPException(409, '该独立预算已绑定其他任务，请配置新预算或勾选“忽略本次任务预算限制”')
        for task in inputs['tasks']:
            route_compilation(task['compilation'], execution_route(
                settings, run.id, body.target_id, task['dataset']))
        account.policy = {**account.policy, 'run_id': str(run.id)}
        frozen['model_budget'] = {k: budget_config[k] for k in
                                  ('budget_id', 'deadline', 'limits_cny')}
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
                latest={"source": "executor_lifecycle", "tool_status": "pending", "task_name": str(child_id), "observed_at": datetime.now(UTC).isoformat(), "snapshot_kind": "live", "collection_status": "waiting_tool", "stale": False, "finish_count": None, "total_count": len(item["samples"]), "progress_description": "监控已启用，等待远程作业启动"},
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
