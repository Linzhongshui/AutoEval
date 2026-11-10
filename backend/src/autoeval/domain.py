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


def check_transition(before: RunState, after: RunState) -> None:
    if before != after and after not in TRANSITIONS.get(before, set()):
        raise ValueError(f"Invalid run transition: {before} -> {after}")
