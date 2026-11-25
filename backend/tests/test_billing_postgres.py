import asyncio
import json
import uuid
from decimal import Decimal

from sqlalchemy import delete

from autoeval.billing import BudgetAccount, BudgetRequest
from autoeval.billing.ledger import BudgetBlocked, finish_request, recover_inflight, reserve_request
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.db import create_database
from autoeval.infrastructure.models import EvaluationRun

R = {"unit_tokens": 1000000, "standard": {"input_miss": "1", "input_hit": "0.1", "output": "1"}}


async def main():
    e, ss = create_database(get_settings())
    budget_id = uuid.uuid4()
    async with ss() as db, db.begin():
        run_id = uuid.uuid4()
        db.add(
            EvaluationRun(
                id=run_id,
                trigger_scope="test:budget",
                idempotency_key=str(run_id),
                request_hash="0" * 64,
                state="running",
                run_mode="exploration",
                created_by="TEST-budget-ledger",
            )
        )
        await db.flush()
        db.add(
            BudgetAccount(
                id=budget_id,
                budget_key="ledger-verification-" + uuid.uuid4().hex,
                currency="CNY",
                total_limit=Decimal(2),
                evaluation_limit=Decimal(1),
                analysis_limit=Decimal(1),
                reserved=Decimal(0),
                spent=Decimal(0),
                state="active",
                policy={"enforcement_ready": True},
            )
        )

    async def reserve(key, section="evaluation", dataset="GPQA", bound=100000, concurrency=24):
        try:
            async with ss() as db, db.begin():
                return await reserve_request(
                    db,
                    budget_id=budget_id,
                    run_id=run_id,
                    request_key=key,
                    section=section,
                    dataset=dataset,
                    input_bound=bound,
                    output_bound=bound,
                    rates=R,
                    concurrency=concurrency,
                )
        except BudgetBlocked as ex:
            return str(ex)

    try:
        results = await asyncio.gather(*(reserve(str(i)) for i in range(24)))
        accepted = [r for r in results if isinstance(r, uuid.UUID)]
        assert len(accepted) == 5, results
        assert all(r == "budget_exhausted" or isinstance(r, uuid.UUID) for r in results)
        assert await reserve("0") == "request_already_reserved"
        async with ss() as db, db.begin():
            account = await db.get(BudgetAccount, budget_id)
            account.policy = {**account.policy, "max_requests": 5}
        assert await reserve("over-count", bound=1) == "request_limit_reached"
        async with ss() as db, db.begin():
            account = await db.get(BudgetAccount, budget_id)
            account.policy = {"enforcement_ready": True, "max_requests_by_dataset": {"GPQA": 5}}
        assert await reserve("over-dataset-count", bound=1) == "dataset_request_limit_reached"
        assert (
            await reserve("ungranted-dataset", dataset="DeepSWE")
            == "dataset_request_limit_unconfigured"
        )
        async with ss() as db, db.begin():
            account = await db.get(BudgetAccount, budget_id)
            account.policy = {"enforcement_ready": True}
        async with ss() as db, db.begin():
            assert (
                await finish_request(
                    db, accepted[0], {"prompt_tokens": 1000, "completion_tokens": 1000}, R
                )
                == "settled"
            )
            assert (
                await finish_request(
                    db, accepted[0], {"prompt_tokens": 1000, "completion_tokens": 1000}, R
                )
                == "settled"
            )
        async with ss() as db:
            b = await db.get(BudgetAccount, budget_id)
            assert b.spent == Decimal("0.002") and b.reserved == Decimal("0.8")
        assert isinstance(
            await reserve("analysis", section="analysis", dataset="analysis"), uuid.UUID
        )
        async with ss() as db, db.begin():
            assert await finish_request(db, accepted[1], None, R) == "unresolved"
        assert await reserve("after-unknown") == "budget_not_active"
        async with ss() as db:
            b = await db.get(BudgetAccount, budget_id)
            assert b.state == "blocked" and b.reserved == Decimal("1.0")
        async with ss() as db, db.begin():
            await db.execute(delete(BudgetRequest).where(BudgetRequest.budget_id == budget_id))
            b = await db.get(BudgetAccount, budget_id)
            b.state = "active"
            b.total_limit = 100
            b.evaluation_limit = 99
            b.analysis_limit = 1
            b.spent = 0
            b.reserved = 0
        lanes = await asyncio.gather(
            *(reserve("g" + str(i), concurrency=24) for i in range(24)),
            *(reserve("a" + str(i), dataset="AutomationBench", concurrency=24) for i in range(24)),
        )
        assert all(isinstance(r, uuid.UUID) for r in lanes)
        assert await reserve("overflow-g", concurrency=24) == "concurrency_full"
        assert (
            await reserve("overflow-a", dataset="AutomationBench", concurrency=24)
            == "concurrency_full"
        )
        async with ss() as db, db.begin():
            assert await recover_inflight(db, budget_id) == 48
            b = await db.get(BudgetAccount, budget_id)
            assert b.state == "blocked"
        print(
            json.dumps(
                {
                    "restart_recovery": "48 retained, account blocked",
                    "dataset_concurrency_checks": "24+24, 25th blocked",
                    "concurrent_requests": 24,
                    "accepted": 5,
                    "overspend": False,
                    "duplicate_settlement": "idempotent",
                    "unknown_usage": "retained_and_blocked",
                    "model_calls": 0,
                }
            )
        )
    finally:
        async with ss() as db, db.begin():
            await db.execute(delete(BudgetRequest).where(BudgetRequest.budget_id == budget_id))
            await db.execute(delete(BudgetAccount).where(BudgetAccount.id == budget_id))
            await db.execute(delete(EvaluationRun).where(EvaluationRun.id == run_id))
        await e.dispose()


import os

import pytest


@pytest.mark.skipif(os.getenv("AE_INFRA_TEST") != "1", reason="Requires migrated real PostgreSQL")
@pytest.mark.asyncio
async def test_real_postgres_budget_accounting():
    await main()
