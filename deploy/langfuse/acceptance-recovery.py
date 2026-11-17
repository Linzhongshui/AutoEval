"""Synthetic auth-failure/retry fixture; never invokes a model or modifies real runs."""

import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

import autoeval.langfuse_integration as integration
from autoeval.config import get_settings
from autoeval.datasets import canonical_manifest
from autoeval.db import create_database
from autoeval.models import EvaluationRun, RunSnapshot
from autoeval.unified_outputs import archive_output


async def main():
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        raise RuntimeError("Development/test only")
    engine, sessions = create_database(settings)
    run_id = uuid.uuid4()
    try:
        snapshot = {
            "execution_origin": "simulation",
            "remote_model": "fixture-auth-recovery",
            "samples": [{"sample_id": "fixture-auth"}],
        }
        async with sessions() as session, session.begin():
            session.add(
                EvaluationRun(
                    id=run_id,
                    trigger_scope="local-operator:evaluation",
                    idempotency_key=str(run_id),
                    request_hash="b" * 64,
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
        body = {
            "schema_version": 1,
            "tool": "ais_bench",
            "subcommand": "harbor_agent",
            "case_count": 1,
            "cases": [
                {
                    "dataset": "AutomationBench",
                    "case_id": "fixture-auth",
                    "attempt": 1,
                    "status": "success",
                    "score": 1,
                    "harbor_artifact": json.loads(Path(sys.argv[1]).read_text()),
                }
            ],
        }
        # Hold only this fixture's dispatch so a deliberately bad credential is
        # tested first; production worker settings and other runs are untouched.
        original = integration.intent
        integration.intent = lambda *args: None
        try:
            await archive_output(
                sessions,
                settings,
                run_id,
                "auth-recovery",
                canonical_manifest(body),
                {"AutomationBench": ["fixture-auth"]},
            )
        finally:
            integration.intent = original
        async with sessions() as session:
            row = await session.scalar(
                select(integration.TraceImport).where(integration.TraceImport.run_id == run_id)
            )
            identifier = str(row.id)
        previous = os.environ.get("AE_LANGFUSE_SECRET_KEY")
        os.environ["AE_LANGFUSE_SECRET_KEY"] = "deliberately-invalid-fixture-key"
        get_settings.cache_clear()
        try:
            await integration.import_harbor_trace(identifier)
        finally:
            if previous is None:
                os.environ.pop("AE_LANGFUSE_SECRET_KEY", None)
            else:
                os.environ["AE_LANGFUSE_SECRET_KEY"] = previous
            get_settings.cache_clear()
        async with sessions() as session:
            row = await session.get(integration.TraceImport, uuid.UUID(identifier))
            assert row.status == "failed" and row.trace_id is None
        print(
            json.dumps(
                {
                    "run_id": str(run_id),
                    "import_id": identifier,
                    "status": "failed",
                    "model_requests": 0,
                }
            )
        )
    finally:
        await engine.dispose()


asyncio.run(main())
