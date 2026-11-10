"""Read-only drift detector; never releases resources or infers task completion."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.models import EvaluationRun

log = logging.getLogger(__name__)


async def serve():
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        while True:
            async with sessions() as session:
                ids = await session.scalars(
                    select(EvaluationRun.id)
                    .where(
                        EvaluationRun.state.in_(["accepted", "queued"]),
                        EvaluationRun.created_at < datetime.now(UTC) - timedelta(minutes=5),
                    )
                    .limit(100)
                )
                for run_id in ids:
                    log.warning("Stale run requires investigation: %s", run_id)
            await asyncio.sleep(60)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
