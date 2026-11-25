"""Request schemas shared by planning and evaluation routes."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ResourceRef(Strict):
    resource_id: uuid.UUID
    resource_kind: Literal["docker_local", "customer_ssh"]


class ProbeInput(ResourceRef):
    target_id: uuid.UUID
    concurrency: list[int] = Field(default_factory=lambda: [1, 2, 4, 8], min_length=1, max_length=7)
    requests_per_level: int = Field(default=2, ge=1, le=64)
    prompt_tokens: int = Field(default=512, ge=1, le=4096)
    max_tokens: int = Field(default=512, ge=1, le=4096)

    @model_validator(mode="after")
    def levels(self):
        if sorted(set(self.concurrency)) != self.concurrency or any(
            not 1 <= n <= 64 for n in self.concurrency
        ):
            raise ValueError("Unique increasing concurrency levels in 1..64 required")
        return self


class TaskInput(Strict):
    concurrency: int | None = Field(default=None, ge=1, le=256)
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    compilation_id: uuid.UUID
    manifest_id: uuid.UUID
    dataset: Literal["GPQA", "MMMU-Pro", "DeepSWE", "AutomationBench"]

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        value = handler(self)
        # Preserve old request hashes when callers do not supply the new optional setting.
        if self.concurrency is None:
            value.pop("concurrency", None)
        return value


class PlanInput(ResourceRef):
    resource_kind: Literal["customer_ssh"]
    resource_ids: list[uuid.UUID] = Field(default_factory=list, max_length=16)
    ignore_budget: bool = Field(default=False, strict=True)

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        value = handler(self)
        if not self.resource_ids:
            value.pop("resource_ids", None)
        if not self.ignore_budget:
            value.pop("ignore_budget", None)
        return value

    target_id: uuid.UUID
    throughput_profile_id: uuid.UUID | None = None
    tasks: list[TaskInput] = Field(min_length=1, max_length=4)
    dataset_concurrency: int = Field(default=1, ge=1)
    recommend: bool = True
    runs: int = Field(default=100, ge=1, le=100)
    seed: int = Field(default=20261111, ge=0, le=2147483647)

    @model_validator(mode="after")
    def unique(self):
        if self.resource_ids and (self.resource_id not in self.resource_ids or len(set(self.resource_ids)) != len(self.resource_ids)):
            raise ValueError("Resource pool must be unique and contain the primary resource")
        if len({t.task_id for t in self.tasks}) != len(self.tasks) or len(
            {t.dataset for t in self.tasks}
        ) != len(self.tasks):
            raise ValueError("Duplicate task or dataset")
        return self


class InferencePerformance(Strict):
    kind: Literal["inference"]
    input_tokens: int = Field(ge=1, le=1048576)
    max_output_tokens: int = Field(ge=1, le=1048576)
    concurrency: int = Field(ge=1, le=256)
    requests: int = Field(ge=1, le=100000)


class AgentXPerformance(Strict):
    kind: Literal["agentx"]
    variant: Literal["256k", "full"]
    run_mode: Literal["smoke", "benchmark"] = "smoke"
    duration: int = Field(ge=1, le=86400)
    concurrency: Annotated[int, Field(ge=1, le=256)] | Annotated[
        list[Annotated[int, Field(ge=1, le=256)]], Field(min_length=1, max_length=256)
    ]
    trace_limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def formal_scope(self):
        if isinstance(self.concurrency, list) and len(set(self.concurrency)) != len(self.concurrency):
            raise ValueError("会话并发档位不能重复")
        if self.run_mode == "benchmark" and (self.duration < 900 or self.trace_limit is not None):
            raise ValueError("benchmark 需要至少 900 秒，trace 数量上限仅适用于 smoke")
        return self


class PerformanceTask(ResourceRef):
    resource_kind: Literal["customer_ssh"]
    target_id: uuid.UUID
    performance: InferencePerformance | AgentXPerformance = Field(discriminator="kind")
    ignore_budget: bool = Field(default=False, strict=True)


class CurveInput(ResourceRef):
    target_id: uuid.UUID
    curve: dict


class ApplyInput(Strict):
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
