"""Archive native bytes under immutable keys and verify report-owned downloads."""

import asyncio
import hashlib
import json
import tempfile
from pathlib import PurePosixPath

from autoeval.catalog.datasets import storage


class CredentialInEvidence(ValueError):
    pass


def save_native(settings, adapter, output, path, run_id, child_id, secrets):
    with tempfile.TemporaryFile() as stream:
        adapter.copy_performance_file(output, path, stream)
        size = stream.tell()
        stream.seek(0)
        checksum = hashlib.sha256()
        overlap = b""
        encoded = [s.encode() for s in secrets if s]
        keep = max(map(len, encoded), default=1)
        while block := stream.read(1024 * 1024):
            if any(secret in overlap + block for secret in encoded):
                raise CredentialInEvidence("Credential in performance evidence")
            checksum.update(block)
            overlap = block[-keep:] if len(block) >= keep else (overlap + block)[-keep:]
        sha = checksum.hexdigest()
        key = f"performance/{run_id}/{child_id}/{sha}"
        stream.seek(0)
        client = storage(settings)
        try:
            client.upload_fileobj(
                stream, settings.s3_bucket, key, ExtraArgs={"Metadata": {"sha256": sha}}
            )
        finally:
            client.close()
        return {"path": path, "size": size, "sha256": sha, "object_key": key}


async def archive_performance(settings, adapter, job, child, run_id, collected, state, secrets):
    config = child.payload["compilation"]["config"]["params"]
    output, parsed = await adapter.performance_result(job, config["kind"])
    files = []
    restricted = False
    for path in parsed.pop("files"):
        if any(secret and secret in path for secret in secrets):
            restricted = True
            continue
        try:
            files.append(
                await asyncio.to_thread(
                    save_native, settings, adapter, output, path, run_id, child.id, secrets
                )
            )
        except CredentialInEvidence:
            restricted = True
    if restricted or any(
        secret and secret in json.dumps(parsed, ensure_ascii=False) for secret in secrets
    ):
        parsed = {"parse_status": "restricted_evidence", "metrics": [], "csv_preview": []}
    exit_code = collected.get("tool_exit_code")
    ok = state == "succeeded" and exit_code == 0
    if config["kind"] == "agentx" and "levels" in parsed:
        observed = {level["concurrency"]: level for level in parsed["levels"]}
        expected = config["concurrency"]
        levels = [
            observed.pop(
                n, {"concurrency": n, "parse_status": "missing", "metrics": [], "csv_preview": []}
            )
            for n in (expected if isinstance(expected, list) else [expected])
        ]
        complete = not observed and all(
            level["parse_status"] == "success"
            and level.get("status") == "completed"
            and level.get("data_status") == "complete"
            and not level.get("missing_artifacts")
            for level in levels
        )
        if len(levels) == 1 and not observed:
            parsed = levels[0]
        else:
            parsed = {
                "levels": levels,
                "parse_status": "success" if complete else "partial",
                "metrics": [],
                "csv_preview": [],
            }
        ok = ok and complete
    elif config["kind"] == "inference":
        ok = (
            ok
            and parsed["parse_status"] == "success"
            and (
                parsed.get("successful_requests")
                == config["requests"]
                == parsed.get("total_requests")
            )
        )
    else:
        ok = False
    summary = {
        "accuracy": None,
        "validity": "complete" if ok else "partial",
        "performance": {**parsed, "tool_exit_code": exit_code, "files": files},
    }
    return ("failed" if state == "succeeded" and not ok else state), summary


def check_files(settings, files, verify_summary_bytes=False):
    client = storage(settings)
    try:
        for file in files:
            header = client.head_object(Bucket=settings.s3_bucket, Key=file["object_key"])
            if (
                header["ContentLength"] != file["size"]
                or header["Metadata"].get("sha256") != file["sha256"]
            ):
                return False
            if verify_summary_bytes and "agentx_raw" not in PurePosixPath(file["path"]).parts:
                source = client.get_object(Bucket=settings.s3_bucket, Key=file["object_key"])[
                    "Body"
                ]
                try:
                    checksum = hashlib.sha256()
                    for chunk in source.iter_chunks(chunk_size=1024 * 1024):
                        checksum.update(chunk)
                    if checksum.hexdigest() != file["sha256"]:
                        return False
                finally:
                    source.close()
        return True
    finally:
        client.close()


def verified_csv(settings, report, path):
    files = report.summary.get("performance", {}).get("files", [])
    reference = next((f for f in files if f["path"] == path), None)
    if not reference or PurePosixPath(path).suffix.lower() != ".csv":
        raise KeyError(path)
    client = storage(settings)
    destination = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)  # noqa: SIM115 -- handed to the streaming response
    try:
        response = client.get_object(Bucket=settings.s3_bucket, Key=reference["object_key"])
        source = response["Body"]
        checksum = hashlib.sha256()
        try:
            for chunk in source.iter_chunks(chunk_size=1024 * 1024):
                destination.write(chunk)
                checksum.update(chunk)
        finally:
            source.close()
        if destination.tell() != reference["size"] or checksum.hexdigest() != reference["sha256"]:
            raise ValueError("Performance CSV integrity mismatch")
        destination.seek(0)
        return destination
    except BaseException:
        destination.close()
        raise
    finally:
        client.close()
