from enum import StrEnum


class RunState(StrEnum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"


TRANSITIONS = {
    RunState.ACCEPTED: {RunState.QUEUED, RunState.CANCELLING, RunState.FAILED},
    RunState.QUEUED: {RunState.PREPARING, RunState.CANCELLING, RunState.FAILED},
    RunState.PREPARING: {RunState.RUNNING, RunState.CANCELLING, RunState.FAILED},
    RunState.RUNNING: {RunState.AGGREGATING, RunState.CANCELLING, RunState.FAILED},
    RunState.AGGREGATING: {RunState.COMPLETED, RunState.CANCELLING, RunState.FAILED},
    RunState.CANCELLING: {RunState.CANCELLED},
}

# External values below are frozen: API payloads, snapshots and reports keep
# these strings even though the vocabulary now lives in one module.
RUN_TERMINAL = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED})


class DatasetState(StrEnum):
    PENDING = "pending"
    SUBMITTING = "submitting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNRESOLVED = "unresolved"


DATASET_TERMINAL = frozenset({DatasetState.SUCCEEDED, DatasetState.FAILED, DatasetState.CANCELLED})
DATASET_ACTIVE = frozenset(
    {DatasetState.SUBMITTING, DatasetState.RUNNING, DatasetState.UNRESOLVED}
)


class ScoringStatus(StrEnum):
    """Scoring outcome, recorded independently of execution success."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvidenceStatus(StrEnum):
    """Report-object health, independent of immutable execution validity."""

    VERIFIED = "verified"
    NOT_CHECKED = "not_checked"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


def check_transition(before: RunState, after: RunState) -> None:
    if before != after and after not in TRANSITIONS.get(before, set()):
        raise ValueError(f"Invalid run transition: {before} -> {after}")
