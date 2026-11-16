"""Compatibility exports; implementation moved to autoeval.reporting."""

from autoeval.reporting.leaderboards import (
    LeaderboardEntry,
    LeaderboardGroup,
    leaderboard,
    rank_leaderboard,
    router,
)

__all__ = [
    "LeaderboardEntry",
    "LeaderboardGroup",
    "leaderboard",
    "rank_leaderboard",
    "router",
]
