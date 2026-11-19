"""Start the local future-only probe consumer without locale-sensitive shell dates.

Run from backend/: uv run python scripts/start_probe_worker.py
Existing historical intents remain excluded. This starts no new probe by itself.
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.db import create_database
from autoeval.planning.probe_dispatch import consumer_ready


async def ready():
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session:
            return await consumer_ready(session)
    finally:
        await engine.dispose()


def main():
    if asyncio.run(ready()):
        print("Probe consumer is already ready; no duplicate process started")
        return
    root = Path(__file__).resolve().parents[1]
    logs = root.parent / ".screenshots"
    logs.mkdir(exist_ok=True)
    config = logs / "probe-worker-future.json"
    saved = json.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
    cutoff = datetime.fromisoformat(saved["accept_after"]) if saved else datetime.now(UTC)
    if cutoff.tzinfo is None:
        raise ValueError("Probe cutoff must include timezone; do not guess historical boundaries")
    environment = dict(
        os.environ, AE_PLANNING_JOB_KINDS="probe", AE_PLANNING_PROBE_ACCEPT_AFTER=cutoff.isoformat()
    )
    with (
        (logs / "probe-worker-future.stdout.log").open("ab") as out,
        (logs / "probe-worker-future.stderr.log").open("ab") as err,
    ):
        process = subprocess.Popen(
            [sys.executable, "-m", "autoeval.planning.planning_worker"],
            cwd=root,
            env=environment,
            stdout=out,
            stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    config.write_text(
        json.dumps({"pid": process.pid, "accept_after": cutoff.isoformat()}), encoding="utf-8"
    )
    print(
        "Probe consumer launched; check readiness before submitting. Historical cutoff preserved."
    )


if __name__ == "__main__":
    main()
