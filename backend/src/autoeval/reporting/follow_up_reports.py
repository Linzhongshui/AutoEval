"""Build a task report against the original manifest from selected case evidence."""

import asyncio
from types import SimpleNamespace

from autoeval.catalog.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.reporting.task_reports import checksum, dataset_context, scored_summary


async def build_follow_up_report(settings, run_id, frozen, case_evidence, historical_state):
    """Each identity maps to the evidence selected from a single execution group."""
    datasets = []
    for task in frozen["inputs"]["tasks"]:
        dataset = task["dataset"]
        cases = []
        index = []
        for sample in task["samples"]:
            sample_id = sample["sample_id"]
            records = case_evidence.get((dataset, sample_id), ())
            refs = []
            for record in records:
                evidence = await asyncio.to_thread(read_manifest, settings, record)
                if (
                    evidence.get("dataset_key") != dataset
                    or evidence.get("sample_id") != sample_id
                    or evidence.get("attempt_no") != record.attempt_no
                ):
                    raise ValueError("Archived case identity differs from the report selection")
                cases.append(
                    {
                        **evidence["raw"],
                        "dataset": dataset,
                        "case_id": sample_id,
                        "attempt": record.attempt_no,
                    }
                )
                refs.append(
                    {
                        "id": str(record.id),
                        "object_key": record.object_key,
                        "sha256": record.sha256,
                    }
                )
            index.append({"sample_id": sample_id, "attempts": refs})
        combined = {
            "schema_version": 1,
            "tool": "ais_bench",
            "subcommand": task["compilation"]["config"]["subcommand"],
            "cases": cases,
            "case_count": len(cases),
        }
        raw = canonical_manifest(combined)
        summary = scored_summary(raw, task, require_attempt_group=True)
        sha = checksum(combined)
        key = f"reports/{run_id}/datasets/{sha}.json"
        await asyncio.to_thread(write_manifest, settings, key, raw)
        await asyncio.to_thread(
            read_manifest, settings, SimpleNamespace(object_key=key, sha256=sha)
        )
        datasets.append(
            {
                "dataset_key": dataset,
                "summary": summary,
                "validity": summary["validity"],
                "context": dataset_context(frozen, task),
                "archive": {"object_key": key, "sha256": sha, "kind": "follow_up"},
                "case_index": index,
            }
        )
    complete = all(dataset["validity"] == "complete" for dataset in datasets)
    summary = {
        "accuracy": None,
        "dataset_count": len(datasets),
        "scoring_status": "succeeded" if complete else "partial",
        "dataset_results": [
            {"dataset_key": dataset["dataset_key"], "summary": dataset["summary"]}
            for dataset in datasets
        ],
    }
    for counter in (
        "expected_samples",
        "executed_attempts",
        "successful_samples",
        "failed_samples",
        "missing_samples",
    ):
        summary[counter] = sum(dataset["summary"][counter] for dataset in datasets)
    return {
        "summary": summary,
        "datasets": datasets,
        "validity": "complete" if complete else "partial",
        "historical_task_state": historical_state,
    }
