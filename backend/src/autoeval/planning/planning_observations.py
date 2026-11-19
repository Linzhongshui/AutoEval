"""Bind native observations and evidence to the frozen dataset execution."""

import asyncio
import re

from sqlalchemy import select

from autoeval.catalog.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.catalog.standard_inputs import digest
from autoeval.evaluation.task_monitor import MonitorBinding, save_observation
from autoeval.reporting.models import UnifiedArtifact
from autoeval_runtime.native_predictions import selected


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
    if not progress or progress.get("source") not in {"aisbench_native_predictions", "harbor_result_files"}:
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
    source = progress["source"]
    task = {
        "task_name": str(child_id),
        "status": ("failed" if progress.get("tool_exit_code") else "completed")
        if final
        else "running",
        "process_id": progress.get("process_id"),
        "start_time": progress.get("start_time"),
        "finish_count": progress.get("finish_count"),
        "total_count": progress.get("total_count") if progress.get("total_count") is not None else (binding.latest or {}).get("total_count"),
        "progress_description": "Harbor 已写出终态 trial；评分结果独立归档" if source == "harbor_result_files" else "已完成原生预测记录；评分结果独立归档",
    }
    await save_observation(
        sessions,
        settings,
        binding.id,
        task,
        source,
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


async def publish_lifecycle(sessions, settings, run_id, child, state, *, final=False):
    """Always observe the owned remote job; never invent native sample progress or PID."""
    from datetime import UTC, datetime

    async with sessions() as session:
        binding = await session.scalar(select(MonitorBinding).where(
            MonitorBinding.run_id == run_id,
            MonitorBinding.identity["child_id"].astext == str(child.id),
        ))
    if binding is None:
        return  # Historical runs are not assigned fabricated monitor bindings.
    if not final and binding.latest and binding.latest.get("source") != "executor_lifecycle":
        return  # Keep a more precise native observation instead of replacing it.
    latest = binding.latest or {}
    native = latest.get("source") in {"aisbench_native_predictions", "harbor_result_files"}
    task = {
        "task_name": str(child.id), "status": state,
        "total_count": len(child.payload["samples"]),
        "finish_count": latest.get("finish_count") if native else None,
        "process_id": latest.get("process_id") if native else None,
        "start_time": latest.get("tool_start_time") if native else None,
        "progress_description": "远程作业状态；原生样本计数未返回" if not native else latest.get("progress_description"),
    }
    await save_observation(sessions, settings, binding.id, task,
        latest["source"] if native else "executor_lifecycle",
        datetime.now(UTC).isoformat(), kind="final" if final else "live")
