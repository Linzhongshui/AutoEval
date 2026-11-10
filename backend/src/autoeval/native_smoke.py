"""Explicit single-request development smoke; never a benchmark or Release result."""

import argparse
import asyncio
import hashlib
import json
import subprocess
import uuid

from sqlalchemy import delete

from autoeval.case_history import AttemptEvidence, AttemptInput, begin_attempt, finish_attempt
from autoeval.config import get_settings
from autoeval.datasets import canonical_manifest
from autoeval.db import create_database
from autoeval.domain import RunState, check_transition
from autoeval.models import EvaluationRun, RunEvent, RunSnapshot
from autoeval.resources import ResourceBinding, inspect_executor
from autoeval.run_activities import record_unresolved
from autoeval.runs import DiagnosticResult, ExecutionLease
from autoeval.secrets import FileSecretStore
from autoeval.targets import TargetBinding, validate_url

FIXTURE = {"question": "What is 2 + 2?", "A": "4", "B": "3", "C": "2", "D": "1", "answer": "A"}


def invoke(settings, container_id, payload):
    # Secret travels on stdin only; never argv, environment, source, snapshot or log.
    command = [
        settings.docker_executable,
        "exec",
        "-i",
        "-e",
        "PYTHONPATH=/work/tools/aisbench/site-packages:/work/tools/aisbench/source",
        container_id,
        "python",
        "/work/tools/aisbench/bridge.py",
        "/work/tools/aisbench/source",
        "/work/tools/aisbench/lock.json",
    ]
    output = subprocess.run(
        command, input=json.dumps(payload).encode(), capture_output=True, timeout=90, check=True
    )
    return json.loads(output.stdout)


async def run_smoke(target_id, resource_id):
    settings = get_settings()
    engine, sessions = create_database(settings)
    run_id = None
    try:
        async with sessions() as session:
            target = await session.get(TargetBinding, target_id)
            resource = await session.get(ResourceBinding, resource_id)
            if target is None or resource is None:
                raise ValueError("Registered target and resource required")
            validate_url(target.base_url, settings.allowed_model_hosts)
            if (
                target.base_url.rstrip("/") != "https://api.deepseek.com"
                or target.remote_model != "deepseek-flash"
            ):
                raise ValueError("Smoke currently supports official deepseek-flash only")
        current = await asyncio.to_thread(
            inspect_executor, settings.docker_executable, resource.container_id
        )
        if not current["running"] or current["image_id"] != resource.image_id:
            raise ValueError("Executor identity mismatch")
        prompt_result = await asyncio.to_thread(
            invoke,
            settings,
            resource.container_id,
            {"operation": "prompt_gpqa_0shot", "sample": FIXTURE},
        )
        frozen = {
            "schema_version": "native-smoke.v1",
            "fixture_only": True,
            "target_id": str(target.id),
            "model_version_id": str(target.model_version_id),
            "base_url": target.base_url,
            "remote_model": target.remote_model,
            "resource_id": str(resource.id),
            "container_id": resource.container_id,
            "image_id": resource.image_id,
            "tool_revision": prompt_result["tool_revision"],
            "sample": FIXTURE,
            "max_tokens": 32,
            "retry_count": 0,
            "generation": {"temperature": 0, "top_p": 1, "thinking": {"type": "disabled"}},
        }
        async with sessions() as session, session.begin():
            run = EvaluationRun(
                trigger_scope="local-operator:native-smoke",
                idempotency_key=uuid.uuid4().hex,
                request_hash=hashlib.sha256(canonical_manifest(frozen)).hexdigest(),
                run_mode="exploration",
                created_by="local-operator",
                state="accepted",
            )
            session.add(run)
            await session.flush()
            run_id = run.id
            session.add(ExecutionLease(container_id=resource.container_id, run_id=run_id))
            session.add(
                RunSnapshot(
                    run_id=run_id,
                    schema_version="native-smoke.v1",
                    canonical_body=frozen,
                    sha256=run.request_hash,
                )
            )
            session.add(
                RunEvent(run_id=run_id, seq=1, type="accepted", body={"fixture_only": True})
            )
            for state in ("queued", "preparing", "running"):
                check_transition(RunState(run.state), RunState(state))
                run.state = state
                run.projection_version += 1
                session.add(
                    RunEvent(
                        run_id=run_id,
                        seq=run.projection_version,
                        type=state,
                        body={"fixture_only": True},
                    )
                )
        attempt_id = await begin_attempt(
            sessions,
            AttemptInput(
                run_id=run_id,
                dataset_key="native-gpqa-fixture",
                sample_id="arithmetic-fixture-1",
                attempt_no=1,
                operation_key="request-1",
            ),
        )
        credential = FileSecretStore(settings.secret_store_path).get(target.credential_ref)
        result = await asyncio.to_thread(
            invoke,
            settings,
            resource.container_id,
            {
                "operation": "infer_gpqa_smoke",
                "sample": FIXTURE,
                "base_url": target.base_url.rstrip("/"),
                "model": target.remote_model,
                "max_tokens": 32,
                "api_key": credential,
            },
        )
        await finish_attempt(
            sessions,
            settings,
            attempt_id,
            AttemptEvidence(
                state=result["state"],
                prompt=result["prompt"],
                response=result["response"],
                finish_reason=result["finish_reason"],
                error_code=result["error_code"],
            ),
        )
        async with sessions() as session, session.begin():
            run = await session.get(EvaluationRun, run_id)
            states = ("aggregating", "completed") if result["state"] == "succeeded" else ("failed",)
            for state in states:
                check_transition(RunState(run.state), RunState(state))
                run.state = state
                run.projection_version += 1
                session.add(
                    RunEvent(
                        run_id=run_id,
                        seq=run.projection_version,
                        type=state,
                        body={"fixture_only": True},
                    )
                )
            session.add(
                DiagnosticResult(
                    run_id=run_id,
                    summary={
                        "fixture_only": True,
                        "diagnostic_only": True,
                        "model_called": True,
                        "gate_status": "not_applicable",
                        "usage": result["usage"],
                        "native_fixture_scoring": result.get("scoring"),
                    },
                )
            )
            await session.execute(delete(ExecutionLease).where(ExecutionLease.run_id == run_id))
        return {
            "run_id": str(run_id),
            "attempt_id": str(attempt_id),
            "state": run.state,
            "fixture_only": True,
            "usage": result["usage"],
        }
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        # No blind retries. If transport/archival is uncertain keep the recorded
        # started attempt and lease for investigation; do not hide its existence.
        if run_id is not None:
            await record_unresolved(sessions, run_id)
        return {
            "run_id": str(run_id) if run_id else None,
            "state": "unresolved",
            "retry_sent": False,
        }
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="One real model request, max32 output tokens, no retry, fixture only"
    )
    parser.add_argument("--target-id", type=uuid.UUID, required=True)
    parser.add_argument("--resource-id", type=uuid.UUID, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_smoke(args.target_id, args.resource_id))))


if __name__ == "__main__":
    main()
