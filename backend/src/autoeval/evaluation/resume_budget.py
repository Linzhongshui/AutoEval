"""Check that a follow-up uses the original authorization and budget."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select

from autoeval.billing.models import BudgetAccount, BudgetRequest
from autoeval.billing.transport import budget_ignored
from autoeval.resources.models import TargetBinding
from autoeval.resources.targets import validate_url


async def follow_up_target_blocker(session, settings, frozen):
    inputs = frozen.get("inputs") or {}
    target_id = inputs.get("target_id")
    identity = inputs.get("target") or {}
    if not target_id or not identity:
        return "target_unavailable"
    target = await session.get(TargetBinding, target_id)
    if (
        target is None
        or target.remote_model != identity.get("model")
        or target.base_url != identity.get("base_url")
    ):
        return "target_unavailable"
    try:
        validate_url(target.base_url, settings.allowed_model_hosts)
    except HTTPException:
        return "target_unavailable"
    return None


def round_budget_snapshot(frozen, operation, accepted_at):
    """Give an explicitly confirmed unmetered Case retry its own execution window."""
    if operation != "case_retry" or not budget_ignored(frozen):
        return frozen
    deadline = accepted_at + timedelta(hours=24)
    return {
        **frozen,
        "model_budget": {**frozen["model_budget"], "execution_deadline": deadline.isoformat()},
    }


async def follow_up_budget_blocker(session, settings, run_id, frozen):
    budget = frozen.get("model_budget") or {}
    ignored = budget_ignored(frozen)
    deadline = budget.get("execution_deadline" if ignored else "deadline")
    if deadline and datetime.now(UTC) >= datetime.fromisoformat(deadline):
        return "budget_expired"
    if ignored:
        return None
    budget_id = budget.get("budget_id")
    config_path = getattr(settings, "billing_execution_config", None)
    if not budget_id:
        return "budget_unavailable" if config_path else None
    if not config_path:
        return "budget_unavailable"
    try:
        configured_id = json.loads(Path(config_path).read_text())["budget_id"]
        if uuid.UUID(configured_id) != uuid.UUID(budget_id):
            return "budget_unavailable"
    except (OSError, ValueError, TypeError, KeyError):
        return "budget_unavailable"
    account = await session.get(BudgetAccount, uuid.UUID(budget_id))
    if account is None or account.state != "active" or account.policy.get("run_id") != str(run_id):
        return "budget_unavailable"
    evaluation_usage = await session.scalar(
        select(
            func.coalesce(
                func.sum(func.coalesce(BudgetRequest.actual_cost, BudgetRequest.reserved_cost)), 0
            )
        ).where(
            BudgetRequest.budget_id == account.id,
            BudgetRequest.section == "evaluation",
        )
    )
    if account.spent + account.reserved >= account.total_limit:
        return "budget_exhausted"
    if evaluation_usage >= account.evaluation_limit:
        return "budget_exhausted"
    return None
