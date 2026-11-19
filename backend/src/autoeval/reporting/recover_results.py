"""Offline native-evidence recovery. No executor or paid client is invoked.

Run in the API environment with a protected JSON mapping trial -> native file text:
python -m autoeval.reporting.recover_results RUN_UUID NATIVE_JSON --reason TEXT
"""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import select

from autoeval.catalog.datasets import canonical_manifest, read_manifest
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.db import create_database
from autoeval.infrastructure.models import RunSnapshot
from autoeval.planning.models import PlanningArtifact
from autoeval.reporting.task_reports import (
    archive_revision,
    publish_task_report,
    restore_native_scores,
)


async def recover(args):
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session, session.begin():
            rid = uuid.UUID(args.run_id)
            snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == rid))
            task = next(
                t
                for t in snapshot.canonical_body["inputs"]["tasks"]
                if t["dataset"] == "AutomationBench"
            )
            artifacts = (
                await session.scalars(
                    select(PlanningArtifact).where(
                        PlanningArtifact.kind == "raw_result",
                        PlanningArtifact.payload["run_id"].astext == str(rid),
                        PlanningArtifact.payload["task_id"].astext == task["task_id"],
                    )
                )
            ).all()
            if not artifacts or len({a.sha256 for a in artifacts}) != 1:
                raise ValueError("Exactly one distinct original raw result hash required")
            original = await asyncio.to_thread(read_manifest, settings, artifacts[0])
            result, hashes = restore_native_scores(
                original["result"],
                task,
                json.loads(Path(args.native_json).read_text(encoding="utf-8")),
            )
            revision = await archive_revision(
                session,
                settings,
                rid,
                "AutomationBench",
                canonical_manifest(result),
                reason=args.reason,
                source_hashes=hashes,
            )
            revision.provenance = {
                **revision.provenance,
                "original_raw_result_sha256": artifacts[0].sha256,
                "original_artifact_ids": sorted(str(a.id) for a in artifacts),
            }
            report = await publish_task_report(session, settings, rid, revision_ids=[revision.id])
            print(
                json.dumps(
                    {
                        "revision_id": str(revision.id),
                        "report_id": str(report.id),
                        "report_sha256": report.sha256,
                        "summary": revision.summary,
                    }
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("native_json")
    parser.add_argument("--reason", required=True)
    asyncio.run(recover(parser.parse_args()))
