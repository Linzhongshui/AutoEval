import asyncio
import hashlib
import math
import subprocess
import uuid
from types import SimpleNamespace

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import delete, select
from temporalio import activity

from autoeval.case_history import (
    AttemptEvidence,
    AttemptInput,
    CaseExecutionRecord,
    begin_attempt,
    finish_attempt,
)
from autoeval.config import get_settings
from autoeval.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.db import create_database
from autoeval.domain import RunState, check_transition
from autoeval.evaluations import EvaluationReport
from autoeval.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.native_smoke import invoke
from autoeval.resources import inspect_executor
from autoeval.run_activities import record_unresolved, transition
from autoeval.runs import ExecutionLease
from autoeval.secrets import FileSecretStore
from autoeval.targets import TargetBinding


@activity.defn
async def execute_gpqa_exploration(run_id: str):
    identifier = uuid.UUID(run_id)
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session, session.begin():
            snapshot = await session.scalar(
                select(RunSnapshot).where(RunSnapshot.run_id == identifier)
            )
            frozen = snapshot.canonical_body
            # Redelivery must never replay a potentially billable request. An
            # existing attempt requires evidence-based recovery, not resubmission.
            existing = await session.scalar(
                select(CaseExecutionRecord.id)
                .where(CaseExecutionRecord.run_id == identifier)
                .limit(1)
            )
            row = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == identifier).with_for_update()
            )
            if row.state in {"completed", "failed", "cancelled"}:
                return {"state": row.state}
            if existing or row.state != "accepted":
                return {"state": "unresolved"}
            target = await session.get(TargetBinding, uuid.UUID(frozen["target_id"]))
            credential_ref = target.credential_ref
            row.state = "queued"
            row.projection_version += 1
            session.add(
                RunEvent(run_id=identifier, seq=row.projection_version, type="queued", body={})
            )
        await transition(sessions, identifier, "preparing")
        identity = await asyncio.to_thread(
            inspect_executor, settings.docker_executable, frozen["container_id"]
        )
        if not identity["running"] or identity["image_id"] != frozen["image_id"]:
            raise ValueError("Executor identity changed")
        bundle = await asyncio.to_thread(
            read_manifest, settings, SimpleNamespace(**frozen["dataset_content"])
        )
        members = {s["sample_id"]: s for s in bundle["samples"]}
        credential = FileSecretStore(settings.secret_store_path).get(credential_ref)
        await transition(sessions, identifier, "running")
        attempts, predictions, references = [], [], []
        cancelled = False
        for expected in frozen["samples"]:
            activity.heartbeat(run_id)
            async with sessions() as session:
                cancelled = (
                    await session.get(EvaluationRun, identifier)
                ).cancel_requested_at is not None
            if cancelled:
                break
            sample = members[expected["sample_id"]]
            if (
                sample["sha256"] != expected["sha256"]
                or hashlib.sha256(canonical_manifest(sample["native_sample"])).hexdigest()
                != expected["sha256"]
            ):
                raise ValueError("Native sample identity changed")
            prompt = await asyncio.to_thread(
                invoke,
                settings,
                frozen["container_id"],
                {"operation": "prompt_gpqa_0shot", "sample": sample["native_sample"]},
            )
            if prompt["tool_revision"] != frozen["tool"]["revision"]:
                raise ValueError("Native tool revision changed")
            attempt_id = await begin_attempt(
                sessions,
                AttemptInput(
                    run_id=identifier,
                    dataset_key="GPQA",
                    sample_id=expected["sample_id"],
                    attempt_no=1,
                    operation_key="sample:" + expected["sample_id"],
                ),
            )
            result = await asyncio.to_thread(
                invoke,
                settings,
                frozen["container_id"],
                {
                    "operation": "infer_gpqa_smoke",
                    "sample": sample["native_sample"],
                    "base_url": frozen["base_url"].rstrip("/"),
                    "model": frozen["remote_model"],
                    "max_tokens": frozen["parameters"]["output"],
                    "api_key": credential,
                },
            )
            await finish_attempt(
                sessions,
                settings,
                attempt_id,
                AttemptEvidence(
                    state=result["state"],
                    prompt=prompt["prompt"],
                    response=result["response"],
                    finish_reason=result["finish_reason"],
                    error_code=result["error_code"],
                ),
            )
            attempts.append(
                {
                    "sample_id": expected["sample_id"],
                    "attempt_id": str(attempt_id),
                    "state": result["state"],
                    "usage": result["usage"],
                }
            )
            if result["state"] == "succeeded":
                predictions.append(result["response"])
                references.append(sample["native_sample"]["answer"])
        async with sessions() as session:
            cancelled = (
                cancelled
                or (await session.get(EvaluationRun, identifier)).cancel_requested_at is not None
            )
        await transition(sessions, identifier, "cancelling" if cancelled else "aggregating")
        scoring = None
        scoring_status = "not_applicable"
        if predictions:
            try:
                scoring = await asyncio.to_thread(
                    invoke,
                    settings,
                    frozen["container_id"],
                    {
                        "operation": "score_gpqa_0shot",
                        "predictions": predictions,
                        "references": references,
                    },
                )
                accuracy = scoring["native_result"]["accuracy"]
                if (
                    type(accuracy) not in (int, float)
                    or not math.isfinite(accuracy)
                    or not 0 <= accuracy <= 100
                ):
                    raise ValueError("Invalid native metric")
                scoring_status = "succeeded"
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                scoring, scoring_status = None, "failed"
        validity = (
            "complete"
            if len(predictions) == len(frozen["samples"]) and not cancelled
            else "partial"
            if predictions
            else "failed_summary"
        )
        if scoring_status == "failed":
            validity = "invalid"
        summary = {
            "expected_samples": len(frozen["samples"]),
            "executed_attempts": len(attempts),
            "successful_samples": len(predictions),
            "failed_samples": sum(a["state"] == "failed" for a in attempts),
            "missing_samples": len(frozen["samples"]) - len(attempts),
            "cancelled": cancelled,
            "gate_status": "not_applicable",
            "metric_scope": "selected_manifest"
            if validity == "complete"
            else "successful_samples_only",
            "subset_scope": "lite",
            "dataset_samples": frozen["dataset_content"]["sample_count"],
            "accuracy": scoring["native_result"]["accuracy"] if scoring else None,
            "scoring_status": scoring_status,
            "formal_score_eligible": False,
        }
        raw = canonical_manifest(
            {
                "schema_version": "gpqa-report.v1",
                "execution_origin": frozen.get("execution_origin", "unverified"),
                "run_id": run_id,
                "snapshot_sha256": snapshot.sha256,
                "validity": validity,
                "summary": summary,
                "attempts": attempts,
                "native_scoring": scoring,
            }
        )
        digest = hashlib.sha256(raw).hexdigest()
        key = f"reports/{run_id}/{digest}.json"
        await asyncio.to_thread(write_manifest, settings, key, raw)
        async with sessions() as session, session.begin():
            row = await session.scalar(
                select(EvaluationRun).where(EvaluationRun.id == identifier).with_for_update()
            )
            final_state = "cancelled" if cancelled else "completed" if predictions else "failed"
            check_transition(RunState(row.state), RunState(final_state))
            row.state = final_state
            row.projection_version += 1
            session.add(
                RunEvent(
                    run_id=identifier,
                    seq=row.projection_version,
                    type=final_state,
                    body={"validity": validity},
                )
            )
            session.add(
                EvaluationReport(
                    execution_origin=frozen.get("execution_origin", "unverified"),
                    run_id=identifier,
                    validity=validity,
                    snapshot_sha256=snapshot.sha256,
                    summary=summary,
                    object_key=key,
                    sha256=digest,
                )
            )
            await session.execute(delete(ExecutionLease).where(ExecutionLease.run_id == identifier))
        return {"state": final_state, "validity": validity}
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        BotoCoreError,
        ClientError,
        subprocess.SubprocessError,
    ):
        await record_unresolved(sessions, identifier)
        return {"state": "unresolved", "ownership_retained": True}
    finally:
        await engine.dispose()
