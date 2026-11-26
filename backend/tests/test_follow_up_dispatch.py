import os
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from autoeval.entrypoints.dispatcher import deliver_once
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.db import create_database
from autoeval.infrastructure.models import Outbox


@pytest.mark.skipif(not os.getenv("AE_INFRA_TEST"), reason="Requires PostgreSQL")
@pytest.mark.parametrize(
    ("original", "override", "expected"),
    [
        ("autoeval.dataset-containers.v1", None, "autoeval.dataset-containers.v1"),
        (None, None, "demo.workflow.v1"),
        ("original-queue", "pinned-queue", "pinned-queue"),
    ],
)
async def test_follow_up_workflow_queue(original, override, expected):
    run_id, round_id = uuid.uuid4(), uuid.uuid4()
    engine, _ = create_database(get_settings())
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TEMP TABLE outbox (LIKE public.outbox INCLUDING DEFAULTS) ON COMMIT DROP"
                )
            )
            sessions = async_sessionmaker(connection, join_transaction_mode="create_savepoint")
            async with sessions.begin() as session:
                session.add(
                    Outbox(
                        run_id=run_id,
                        kind="START_RUN",
                        dedup_key=f"planned:{run_id}",
                        state="delivered",
                        payload={"workflow_queue": original} if original else {},
                    )
                )
                payload = {"workflow_kind": "evaluation_follow_up", "round_id": str(round_id)}
                if override:
                    payload["workflow_queue"] = override
                session.add(
                    Outbox(
                        run_id=run_id,
                        kind="START_RUN",
                        dedup_key=f"evaluation-round:{round_id}",
                        payload=payload,
                    )
                )
            client = AsyncMock()
            assert await deliver_once(sessions, client, run_id=run_id)
            client.start_workflow.assert_awaited_once()
            assert client.start_workflow.await_args.kwargs["task_queue"] == expected
            assert (
                client.start_workflow.await_args.kwargs["id"]
                == f"demo/run/{run_id}/round/{round_id}"
            )
            assert not await deliver_once(sessions, client, run_id=run_id)
    finally:
        await engine.dispose()
