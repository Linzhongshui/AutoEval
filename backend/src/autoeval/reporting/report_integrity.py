"""Report-object health is independent of immutable historical execution validity."""

import asyncio

from botocore.exceptions import BotoCoreError, ClientError

from autoeval.catalog.datasets import read_manifest


async def report_evidence_status(settings, report, run, snapshot):
    status, _ = await verified_report_body(settings, report, run, snapshot)
    return status


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
            from types import SimpleNamespace

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
                    if scored_summary(canonical_manifest(raw), task) != d["summary"]:
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
    except (ValueError, TypeError, OSError, KeyError, StopIteration):
        return "invalid", None
