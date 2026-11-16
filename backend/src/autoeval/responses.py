"""Shared response envelope models mirroring the current JSON contracts.

Field sets, nullability and pagination shapes must stay byte-compatible with
the hand-written dictionaries the routes used to return; dynamic payloads
(artifact/evidence bodies) intentionally stay ``dict`` so nothing is filtered.
"""

from pydantic import BaseModel


class Accepted(BaseModel):
    accepted: bool


class SubmittedRun(BaseModel):
    run_id: str
    state: str


class TaskStatistics(BaseModel):
    total: int
    active: int
    completed: int
    failed_cancelled: int


class Envelope[T](BaseModel):
    data: T
    request_id: str


class PageEnvelope[T](BaseModel):
    data: list[T]
    next_offset: int | None
    request_id: str


class TotalPageEnvelope[T](BaseModel):
    data: list[T]
    next_offset: int | None
    total: int
    request_id: str


class TaskListEnvelope[T](BaseModel):
    data: list[T]
    statistics: TaskStatistics
    next_offset: int | None
    request_id: str


class LeaderboardEnvelope[T](BaseModel):
    data: list[T]
    excluded_unverified_reports: int
    request_id: str
