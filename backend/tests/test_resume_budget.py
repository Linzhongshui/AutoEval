from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from autoeval.evaluation.resume_budget import follow_up_budget_blocker


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
