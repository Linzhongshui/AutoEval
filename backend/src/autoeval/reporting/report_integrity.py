"""Report-object health is independent of immutable historical execution validity."""

import asyncio
from types import SimpleNamespace

from botocore.exceptions import BotoCoreError, ClientError

from autoeval.catalog.datasets import read_manifest


async def report_evidence_status(settings, report, run, snapshot):
    status, _ = await verified_report_body(settings, report, run, snapshot)
    return status


async def verify_follow_up_cases(settings, dataset, task, combined):
    index = dataset["case_index"]
    if [entry["sample_id"] for entry in index] != [
        sample["sample_id"] for sample in task["samples"]
    ]:
        return False
    cases = []
    seen = set()
    for entry in index:
        for reference in entry["attempts"]:
            if reference["id"] in seen:
                return False
            seen.add(reference["id"])
            record = await asyncio.to_thread(read_manifest, settings, SimpleNamespace(**reference))
            if (
                record.get("schema_version") != "unified-case.v1"
                or record.get("dataset_key") != task["dataset"]
                or record.get("sample_id") != entry["sample_id"]
            ):
                return False
            cases.append(
                {
                    **record["raw"],
                    "dataset": record["dataset_key"],
                    "case_id": record["sample_id"],
                    "attempt": record["attempt_no"],
                }
            )
    return cases == combined["cases"]


async def verified_report_body(settings, report, run, snapshot):
    try:
        body = await asyncio.to_thread(read_manifest, settings, report)
        if (
            not isinstance(body, dict)
            or body.get("schema_version")
            not in {"gpqa-report.v1", "planned-report.v1", "task-report.v2"}
            or body.get("run_id") != str(run.id)
            or body.get("snapshot_sha256") != snapshot.sha256
            or report.snapshot_sha256 != snapshot.sha256
            or body.get("execution_origin") != report.execution_origin
            or body.get("summary") != report.summary
            or body.get("validity") != report.validity
        ):
            return "invalid", None
        if body.get("schema_version") == "task-report.v2":
            from autoeval.catalog.datasets import canonical_manifest
            from autoeval.reporting.task_reports import checksum, dataset_context, scored_summary

            if (
                checksum(snapshot.canonical_body) != snapshot.sha256
                or body["summary"].get("accuracy") is not None
            ):
                return "invalid", None
            tasks = snapshot.canonical_body["inputs"]["tasks"]
            datasets = body.get("datasets", [])
            if len(tasks) != len(datasets) or len({d["dataset_key"] for d in datasets}) != len(
                tasks
            ):
                return "invalid", None
            for task in tasks:
                d = next((d for d in datasets if d["dataset_key"] == task["dataset"]), None)
                if (
                    d is None
                    or d["validity"] != d["summary"]["validity"]
                    or d["context"] != dataset_context(snapshot.canonical_body, task)
                ):
                    return "invalid", None
                if d.get("archive"):
                    raw = await asyncio.to_thread(
                        read_manifest, settings, SimpleNamespace(**d["archive"])
                    )
                    follow_up = (getattr(report, "version", None) or 1) > 1
                    if scored_summary(
                        canonical_manifest(raw), task, require_attempt_group=follow_up
                    ) != d["summary"]:
                        return "invalid", None
                    if follow_up and (
                        body.get("round") != report.version
                        or not await verify_follow_up_cases(settings, d, task, raw)
                    ):
                        return "invalid", None
                elif d["validity"] == "complete":
                    return "invalid", None
        return "verified", body
    except ClientError as exc:
        return (
            "missing"
            if exc.response["Error"]["Code"] in {"NoSuchKey", "NoSuchBucket", "404"}
            else "unavailable"
        ), None
    except BotoCoreError:
        return "unavailable", None
    except (AttributeError, ValueError, TypeError, OSError, KeyError, StopIteration):
        return "invalid", None
