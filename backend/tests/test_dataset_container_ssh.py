"""Fixed-output isolation check on an explicitly selected SSH resource and evidence store."""

import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from autoeval.catalog.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.catalog.standard_inputs import digest
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.db import create_database
from autoeval.planning.planning_transport import (
    IsolatedPlanningContainer,
    executor_templates,
)
from autoeval.resources.models import SSHResourceBinding
from autoeval.resources.ssh_resources import connection_for
from autoeval_runtime.planning_runtime import ADAPTOR_REVISION

# Exclusive creation at the same absolute path detects a shared or reused writable layer.
FIXTURE_RUNTIME = b"""
import json
from pathlib import Path


def validate_spec(spec):
    assert spec["kind"] == "adaptor" and spec["credential"] == "fixture-only"


def execute(folder, spec):
    cases = spec["case_contract"]
    result = {"child": folder.name, "run": cases["run"], "dataset": cases["dataset"],
              "cases": cases["ids"], "model_called": False}
    output = Path("/tmp/autoeval-isolation-cases.json")
    with output.open("x") as stream:
        json.dump(result, stream)
    return json.loads(output.read_text())


def controlled_failure_reason(spec, exc):
    return "fixture_failed"
"""


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("AE_ISOLATION_RESOURCE_ID"), reason="Explicit SSH resource required"
)
async def test_new_runs_and_datasets_have_separate_containers_and_archives():
    settings = get_settings()
    resource_id = uuid.UUID(os.environ["AE_ISOLATION_RESOURCE_ID"])
    template = executor_templates(settings, resource_id)["aisbench"]
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session:
            resource = await session.get(SSHResourceBinding, resource_id)
            connection = connection_for(resource, settings)
    finally:
        await engine.dispose()

    run_a, run_b = str(uuid.uuid4()), str(uuid.uuid4())
    jobs = [(run_a, "GPQA"), (run_a, "MMMU-Pro"), (run_b, "GPQA")]
    adapters = [
        IsolatedPlanningContainer(connection, uuid.uuid4(), {**template, "family": "aisbench"})
        for _ in jobs
    ]

    async def execute_fixture(adapter, run, dataset):
        adapter.files["planning_runtime.py"] = FIXTURE_RUNTIME
        identifier = await adapter.ensure()
        cases = {"run": run, "dataset": dataset, "ids": ["case-1", "case-2"]}
        spec = {
            "kind": "adaptor",
            "compilation": {"adaptor_revision": ADAPTOR_REVISION},
            "tool": {"family": "aisbench"},
            "credential": "fixture-only",
            "case_contract": cases,
        }
        job = await adapter.submit(spec, adapter.owner)
        async with asyncio.timeout(90):
            while (status := await adapter.status(job)).state in {"running", "submitted"}:
                await asyncio.sleep(0.5)
        assert status.state == "succeeded", status
        result = (await adapter.collect(job))["result"]
        expected = {
            "child": adapter.owner,
            "run": run,
            "dataset": dataset,
            "cases": cases["ids"],
            "model_called": False,
        }
        assert result == expected
        key = f"acceptance/r13-isolation/{run}/{adapter.owner}/cases.json"
        await asyncio.to_thread(write_manifest, settings, key, canonical_manifest(result))
        return identifier, SimpleNamespace(object_key=key, sha256=digest(result)), expected

    try:
        # Finish both datasets from run A first. Run B repeats A's GPQA selection.
        evidence = []
        for adapter, (run, dataset) in zip(adapters, jobs, strict=True):
            evidence.append(await execute_fixture(adapter, run, dataset))
        ids = [identifier for identifier, _, _ in evidence]
        assert len(set(ids)) == len(jobs)
        for adapter in adapters:
            assert await adapter.remove()
            assert await asyncio.to_thread(adapter._inspect_owned) is None
        for identifier, archive, expected in evidence:
            assert await asyncio.to_thread(read_manifest, settings, archive) == expected
            print(f"{expected['dataset']} {identifier[:12]} cleaned {archive.object_key}")
    finally:
        await asyncio.gather(*(adapter.remove() for adapter in adapters))
