"""Opt-in synthetic acceptance through platform archival and durable outbox.
Run inside the configured platform container; never executes a benchmark/model.
"""

import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from autoeval.config import get_settings
from autoeval.datasets import canonical_manifest
from autoeval.db import create_database
from autoeval.langfuse_integration import TraceImport
from autoeval.models import EvaluationRun, RunSnapshot
from autoeval.unified_outputs import archive_output


async def main():
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        raise RuntimeError("Synthetic acceptance only supports development/test")
    artifact = json.loads(Path(sys.argv[1]).read_text())
    engine, sessions = create_database(settings)
    run_id = uuid.uuid4()
    try:
        snapshot = {
            "execution_origin": "simulation",
            "remote_model": "fixture-no-model",
            "samples": [
                {"sample_id": x} for x in ["fixture-a", "fixture-missing", "fixture-invalid"]
            ],
            "parameters": {"acceptance": "synthetic ATIF; no model requests"},
        }
        async with sessions() as session, session.begin():
            session.add(
                EvaluationRun(
                    id=run_id,
                    trigger_scope="local-operator:evaluation",
                    idempotency_key=str(run_id),
                    request_hash="a" * 64,
                    run_mode="exploration",
                    created_by="langfuse-synthetic-acceptance",
                    state="completed",
                )
            )
            await session.flush()
            session.add(
                RunSnapshot(
                    run_id=run_id,
                    schema_version="acceptance.v1",
                    canonical_body=snapshot,
                    sha256=hashlib.sha256(canonical_manifest(snapshot)).hexdigest(),
                )
            )
        cases = []
        for sample, attempt, kind in [
            ("fixture-a", 1, "valid"),
            ("fixture-a", 2, "valid"),
            ("fixture-missing", 1, "missing"),
            ("fixture-invalid", 1, "invalid"),
        ]:
            data = json.loads(json.dumps(artifact))
            if kind == "missing":
                data["files"].pop("agent/trajectory.json")
            if kind == "invalid":
                data["files"]["agent/trajectory.json"] = "not-json"
            cases.append(
                {
                    "dataset": "AutomationBench",
                    "case_id": sample,
                    "attempt": attempt,
                    "status": "success",
                    "score": 1,
                    "harbor_artifact": data,
                }
            )
        body = {
            "schema_version": 1,
            "tool": "ais_bench",
            "subcommand": "harbor_agent",
            "case_count": len(cases),
            "cases": cases,
        }
        raw = canonical_manifest(body)
        expected = {"AutomationBench": ["fixture-a", "fixture-missing", "fixture-invalid"]}
        first = await archive_output(sessions, settings, run_id, "acceptance", raw, expected)
        duplicate = await archive_output(sessions, settings, run_id, "acceptance", raw, expected)
        assert first == duplicate
        async with sessions() as session:
            rows = (
                await session.scalars(select(TraceImport).where(TraceImport.run_id == run_id))
            ).all()
            assert len(rows) == 4
        print(
            json.dumps(
                {
                    "run_id": str(run_id),
                    "origin": "simulation",
                    "model_requests": 0,
                    "imports": [str(r.id) for r in rows],
                },
                indent=2,
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
