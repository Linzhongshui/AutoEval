"""Serialized budget accounting. Caller commits reservation before upstream I/O."""

import uuid
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import func, select

from autoeval.billing import BudgetAccount, BudgetRequest
from autoeval.billing_limits import MICRO, maximum_request_cost, reservation_allowed


class BudgetBlocked(ValueError):
    pass


async def reserve_request(
    db,
    *,
    budget_id,
    run_id,
    request_key,
    section,
    dataset,
    input_bound,
    output_bound,
    rates,
    concurrency=24,
):
    account = await db.scalar(
        select(BudgetAccount).where(BudgetAccount.id == budget_id).with_for_update()
    )
    if account is None or account.state != "active" or not account.policy.get("enforcement_ready"):
        raise BudgetBlocked("budget_not_active")
    bound_run = account.policy.get("run_id")
    if bound_run is not None and bound_run != str(run_id):
        raise BudgetBlocked("budget_bound_to_another_run")
    if bound_run is None:
        account.policy = {**account.policy, "run_id": str(run_id)}
    existing = await db.scalar(
        select(BudgetRequest).where(
            BudgetRequest.budget_id == budget_id, BudgetRequest.request_key == request_key
        )
    )
    if existing is not None:
        raise BudgetBlocked("request_already_reserved")
    if section not in ("evaluation", "analysis"):
        raise BudgetBlocked("unknown_budget_section")
    active = await db.scalar(
        select(func.count())
        .select_from(BudgetRequest)
        .where(
            BudgetRequest.budget_id == budget_id,
            BudgetRequest.section == section,
            BudgetRequest.dataset == dataset,
            BudgetRequest.state == "reserved",
        )
    )
    if active >= concurrency:
        raise BudgetBlocked("concurrency_full")
    committed = await db.scalar(
        select(
            func.coalesce(
                func.sum(func.coalesce(BudgetRequest.actual_cost, BudgetRequest.reserved_cost)), 0
            )
        ).where(BudgetRequest.budget_id == budget_id, BudgetRequest.section == section)
    )
    cost = maximum_request_cost(input_bound, output_bound, rates)
    limit = account.evaluation_limit if section == "evaluation" else account.analysis_limit
    if not reservation_allowed(
        account.total_limit, account.spent, account.reserved, cost, limit, committed
    ):
        raise BudgetBlocked("budget_exhausted")
    row = BudgetRequest(
        id=uuid.uuid4(),
        budget_id=budget_id,
        run_id=run_id,
        request_key=request_key,
        section=section,
        dataset=dataset,
        reserved_cost=cost,
        state="reserved",
        usage={
            "price_snapshot": rates,
            "input_token_bound": input_bound,
            "output_token_bound": output_bound,
        },
    )
    account.reserved += cost
    db.add(row)
    await db.flush()
    return row.id


async def finish_request(db, request_id, usage, rates):
    reference = await db.get(BudgetRequest, request_id)
    if reference is None:
        raise BudgetBlocked("reservation_missing")
    account = await db.scalar(
        select(BudgetAccount).where(BudgetAccount.id == reference.budget_id).with_for_update()
    )
    row = await db.scalar(
        select(BudgetRequest)
        .where(BudgetRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.state != "reserved":
        return row.state
    try:
        prompt, output = usage["prompt_tokens"], usage["completion_tokens"]
        if any(type(x) is not int or x < 0 for x in (prompt, output)):
            raise ValueError("invalid_usage")
        # Peak/noncached pricing is an upper-bound settlement, not a provider invoice.
        tier = rates.get("peak", rates.get("standard"))
        cost = (
            (prompt * Decimal(tier["input_miss"]) + output * Decimal(tier["output"])) / 1000000
        ).quantize(MICRO, rounding=ROUND_CEILING)
        if cost > row.reserved_cost:
            raise ValueError("usage_exceeds_reservation")
    except (KeyError, TypeError, ValueError, ArithmeticError):
        row.state = "unresolved"
        if isinstance(usage, dict) and isinstance(usage.get("error_code"), str):
            row.usage = {**(row.usage or {}), "error_code": usage["error_code"][:128]}
        account.state = "blocked"
        return row.state
    account.reserved -= row.reserved_cost
    account.spent += cost
    row.actual_cost = cost
    row.usage = {
        **(row.usage or {}),
        "prompt_tokens": prompt,
        "completion_tokens": output,
        "cost_basis": "conservative_official_upper_bound",
    }
    row.state = "settled"
    return row.state


async def recover_inflight(db, budget_id):
    """A proxy restart cannot prove whether prior reserved requests reached the provider."""
    account = await db.scalar(
        select(BudgetAccount).where(BudgetAccount.id == budget_id).with_for_update()
    )
    if account is None:
        raise BudgetBlocked("budget_missing")
    pending = (
        await db.scalars(
            select(BudgetRequest).where(
                BudgetRequest.budget_id == budget_id, BudgetRequest.state == "reserved"
            )
        )
    ).all()
    for row in pending:
        row.state = "unresolved"
    if pending:
        account.state = "blocked"
    return len(pending)
