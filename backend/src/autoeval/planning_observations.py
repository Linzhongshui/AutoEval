"""Bind native observations and evidence to the frozen dataset execution."""

import asyncio
import re

from sqlalchemy import select

from autoeval.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.native_predictions import selected
from autoeval.standard_inputs import digest
from autoeval.task_monitor import MonitorBinding, save_observation
from autoeval.unified_artifacts import UnifiedArtifact


def case_contract(task):
    aliases = {"GPQA": "GPQA_diamond", "MMMU-Pro": "mmmu_pro"}
    if task["dataset"] not in aliases:
        return None
    params = task["compilation"]["config"]["params"]
    abbr = params["abbr"]
    dataset = params.get("dataset_abbr") or aliases[task["dataset"]]
    if any(
        not isinstance(x, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", x)
        for x in (abbr, dataset)
    ):
        raise ValueError("Invalid native dataset/model abbreviation")
    cases = {str(s["tool_case_id"]): s["sample_id"] for s in task["samples"]}
    if len(cases) != len(task["samples"]):
        raise ValueError("Duplicate frozen tool sample identity")
    return {
        "model_abbr": abbr,
        "dataset_abbr": dataset,
        "case_ids": list(cases),
        "sample_ids": cases,
        "dataset": task["dataset"],
    }


async def publish(sessions, settings, run_id, child_id, progress):
    if not progress or progress.get("source") != "aisbench_native_predictions":
        return
    if progress.get("job_id") != str(child_id):
        raise ValueError("Progress belongs to another dataset execution")
    async with sessions() as session:
        binding = await session.scalar(
            select(MonitorBinding).where(
                MonitorBinding.run_id == run_id,
                MonitorBinding.identity["child_id"].astext == str(child_id),
            )
        )
    if binding is None:
        raise ValueError("Dataset monitor binding missing")
    if (
        binding.latest
        and binding.latest.get("source") == "aisbench_native_predictions"
        and isinstance(progress.get("finish_count"), int)
        and progress["finish_count"] < (binding.latest.get("finish_count") or 0)
    ):
        raise ValueError("Native prediction count regressed; retain last observation")
    final = progress.get("snapshot_kind") == "final"
    task = {
        "task_name": str(child_id),
        "status": ("failed" if progress.get("tool_exit_code") else "completed")
        if final
        else "running",
        "process_id": progress.get("process_id"),
        "start_time": progress.get("start_time"),
        "finish_count": progress.get("finish_count"),
        "total_count": progress.get("total_count"),
        "progress_description": "已完成原生预测记录；评分结果独立归档",
    }
    await save_observation(
        sessions,
        settings,
        binding.id,
        task,
        "aisbench_native_predictions",
        progress["observed_at"],
        kind="final" if final else "live",
    )


async def archive_native(sessions, settings, run_id, child, result, secret):
    contract = case_contract(child.payload)
    files = result.get("native_files")
    if not files:
        return  # Old runtimes have no native attachment; never fabricate content.
    if result.get("case_contract") != contract:
        raise ValueError("Native evidence contract differs from frozen selection")
    selected(files, contract)  # Verify hashes and reject conflicting records.
    bundle = {
        "run_id": str(run_id),
        "child_id": str(child.id),
        "contract": contract,
        "files": files,
    }
    raw = canonical_manifest(bundle)
    if secret and secret.encode() in raw:
        raise ValueError("Credential found in native evidence")
    sha = digest(bundle)
    key = f"native-predictions/{run_id}/{child.id}/{sha}.json"
    async with sessions() as session, session.begin():
        collection = "planning-native:" + str(child.id)
        old = await session.scalar(
            select(UnifiedArtifact).where(
                UnifiedArtifact.run_id == run_id, UnifiedArtifact.collection_key == collection
            )
        )
        if old:
            if old.sha256 != sha:
                raise ValueError("Native archive conflicts with existing evidence")
            await asyncio.to_thread(read_manifest, settings, old)
            return
        await asyncio.to_thread(write_manifest, settings, key, raw)
        row = UnifiedArtifact(
            run_id=run_id,
            collection_key=collection,
            object_key=key,
            sha256=sha,
            manifest={"contract": contract, "child_id": str(child.id)},
        )
        await asyncio.to_thread(read_manifest, settings, row)
        session.add(row)
