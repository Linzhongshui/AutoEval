"""Compatibility exports; implementation moved to autoeval.reporting."""

from autoeval.reporting.case_history import (
    AttemptEvidence,
    AttemptInput,
    CaseExecutionItem,
    CaseExecutionRecord,
    TokenUsage,
    begin_attempt,
    evidence,
    finish_attempt,
    history,
    router,
)

__all__ = [
    "AttemptEvidence",
    "AttemptInput",
    "CaseExecutionItem",
    "CaseExecutionRecord",
    "TokenUsage",
    "begin_attempt",
    "evidence",
    "finish_attempt",
    "history",
    "router",
]
