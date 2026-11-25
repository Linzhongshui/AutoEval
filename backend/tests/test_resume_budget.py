from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from autoeval.evaluation.resume_budget import follow_up_budget_blocker, round_budget_snapshot


@pytest.mark.parametrize("minutes, expected", [(-1, "budget_expired"), (10, None)])
async def test_follow_up_uses_original_execution_deadline(minutes, expected):
    frozen = {
        "inputs": {"ignore_budget": True},
        "model_budget": {
            "mode": "ignored",
            "execution_deadline": (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(),
        },
    }
    assert await follow_up_budget_blocker(None, SimpleNamespace(), None, frozen) == expected


async def test_case_retry_window_uses_persisted_round_time_and_preserves_original():
    now = datetime.now(UTC)
    original = (now - timedelta(days=2)).isoformat()
    frozen = {
        "inputs": {"ignore_budget": True},
        "model_budget": {"mode": "ignored", "execution_deadline": original},
    }
    retry = round_budget_snapshot(frozen, "case_retry", now)
    assert retry["model_budget"]["execution_deadline"] == (now + timedelta(days=1)).isoformat()
    assert await follow_up_budget_blocker(None, SimpleNamespace(), None, retry) is None
    assert frozen["model_budget"]["execution_deadline"] == original
    assert round_budget_snapshot(frozen, "resume", now) is frozen
    overdue = round_budget_snapshot(frozen, "case_retry", now - timedelta(hours=25))
    assert (
        await follow_up_budget_blocker(None, SimpleNamespace(), None, overdue) == "budget_expired"
    )
    metered = {"model_budget": {"deadline": original}}
    assert round_budget_snapshot(metered, "case_retry", now) is metered
    assert (
        await follow_up_budget_blocker(None, SimpleNamespace(), None, metered) == "budget_expired"
    )
