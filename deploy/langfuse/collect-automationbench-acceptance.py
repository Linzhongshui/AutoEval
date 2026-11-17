"""Read-only evidence summary inside the API container; omits prompts and credentials."""

import asyncio
import hashlib
import json
import sys
import tempfile
import uuid
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy import select

from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.langfuse_integration import TraceImport, build_plan, read_manifest, trace_view
from autoeval.unified_outputs import CaseExecutionRecord


async def main():
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session:
            rows = await session.scalars(
                select(TraceImport).where(TraceImport.run_id == uuid.UUID(sys.argv[1]))
            )
            records = []
            for row in rows:
                case = await session.get(CaseExecutionRecord, row.attempt_id)
                artifact = await asyncio.to_thread(read_manifest, settings, row)
                record = {
                    "run_id": str(row.run_id),
                    "attempt_id": str(row.attempt_id),
                    "sample_id": case.sample_id,
                    "attempt_no": case.attempt_no,
                    "case_state": case.state,
                    "artifact_sha256": row.sha256,
                    "files": {
                        name: hashlib.sha256(text.encode()).hexdigest()
                        for name, text in artifact["files"].items()
                    },
                    **trace_view(row, settings),
                }
                if row.status == "succeeded":
                    with tempfile.TemporaryDirectory() as directory:
                        native, plan = build_plan(
                            artifact, Path(directory), str(row.attempt_id), row.content_mode
                        )
                    expected = {format(span.span_id, "016x") for span in plan}
                    observations = []
                    async with httpx.AsyncClient(
                        auth=(
                            settings.langfuse_public_key.get_secret_value(),
                            settings.langfuse_secret_key.get_secret_value(),
                        ),
                        timeout=30,
                    ) as client:
                        cursor = None
                        while True:
                            params = {"traceId": row.trace_id, "limit": 1000}
                            if cursor:
                                params["cursor"] = cursor
                            response = await client.get(
                                settings.langfuse_host + "/api/public/v2/observations",
                                params=params,
                            )
                            response.raise_for_status()
                            body = response.json()
                            observations.extend(body["data"])
                            cursor = (body.get("meta") or {}).get("nextCursor")
                            if not cursor:
                                break
                    observed = {item["id"]: item for item in observations}
                    record.update(
                        native_reward=native.reward,
                        native_named_metrics=native.reward_details,
                        expected_span_roles=dict(Counter(span.role for span in plan)),
                        observation_count=len(observations),
                        all_spans_present=expected <= observed.keys(),
                        unique_observation_ids=len(observed) == len(observations),
                        parent_relationships_match=all(
                            observed.get(format(span.span_id, "016x"), {}).get(
                                "parentObservationId"
                            )
                            == (
                                format(plan[span.parent].span_id, "016x")
                                if span.parent is not None
                                else None
                            )
                            for span in plan
                        ),
                    )
                records.append(record)
            print(json.dumps({"records": records}, indent=2))
    finally:
        await engine.dispose()


asyncio.run(main())
