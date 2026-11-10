"""Strict operator CLI for immutable, approved JSON benchmark baselines."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select

from autoeval.benchmarks import BenchmarkBaseline
from autoeval.config import get_settings
from autoeval.db import create_database


class BaselineInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    baseline_key: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,128}$")
    version: str = Field(min_length=1, max_length=128)
    dataset_key: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,128}$")
    subset_scope: Literal["full", "lite"]
    metric_name: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,128}$")
    unit: str = Field(min_length=1, max_length=32)
    value: float = Field(allow_inf_nan=False)
    direction: Literal["higher_is_better", "lower_is_better"]
    conditions: dict[str, JsonValue]
    source_url: str = Field(pattern=r"^https://[^\s]+$", max_length=1024)
    source_revision: str = Field(min_length=1, max_length=256)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1, max_length=256)


class BaselineBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    baselines: list[BaselineInput] = Field(min_length=1)


class BaselineConflictError(ValueError):
    pass


CONTENT_FIELDS = tuple(BaselineInput.model_fields)


def _content(body):
    return json.dumps(
        body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def _digest(body):
    return hashlib.sha256(_content(body)).hexdigest()


def _identity(body):
    return tuple(
        body[key]
        for key in ("baseline_key", "version", "dataset_key", "subset_scope", "metric_name")
    )


async def import_baselines(session, body):
    """Insert new records or return exact duplicates; never overwrite an identity."""
    bundle = BaselineBundle.model_validate(body)
    imported = []
    pending = {}
    for item in bundle.baselines:
        values = item.model_dump(mode="json")
        identity = _identity(values)
        digest = _digest(values)
        row = pending.get(identity)
        if row is None:
            row = await session.scalar(
                select(BenchmarkBaseline)
                .where(
                    BenchmarkBaseline.baseline_key == values["baseline_key"],
                    BenchmarkBaseline.version == values["version"],
                    BenchmarkBaseline.dataset_key == values["dataset_key"],
                    BenchmarkBaseline.subset_scope == values["subset_scope"],
                    BenchmarkBaseline.metric_name == values["metric_name"],
                )
                .with_for_update()
            )
        if row is not None:
            existing = {key: getattr(row, key) for key in CONTENT_FIELDS}
            if row.content_sha256 != digest or _digest(existing) != digest:
                raise BaselineConflictError("Baseline identity is immutable; content conflicts")
        else:
            row = BenchmarkBaseline(**values, content_sha256=digest)
            session.add(row)
        pending[identity] = row
        imported.append(row)
    return imported


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


async def _import_path(path):
    body = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session, session.begin():
            rows = await import_baselines(session, body)
        return {
            "baselines": [{"id": str(row.id), "content_sha256": row.content_sha256} for row in rows]
        }
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Import approved immutable benchmark baselines")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_import_path(args.input))))


if __name__ == "__main__":
    main()
