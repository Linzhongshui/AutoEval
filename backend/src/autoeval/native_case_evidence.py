"""Read-time enrichment from immutable native predictions; never rewrite case evidence."""

import hashlib
import json
from pathlib import PurePosixPath


def prediction_records(content):
    # AISBench may contain unescaped line breaks within prediction strings.
    # A bounded streaming decoder preserves those bytes and handles multiline records.
    if len(content.encode("utf-8")) > 12 * 1024 * 1024:
        raise ValueError("Prediction file exceeds limit")
    decoder = json.JSONDecoder(strict=False)
    offset = 0
    rows = []
    while offset < len(content):
        while offset < len(content) and content[offset].isspace():
            offset += 1
        if offset == len(content):
            break
        row, offset = decoder.raw_decode(content, offset)
        if not isinstance(row, dict):
            raise TypeError("Prediction record must be an object")
        rows.append(row)
        if len(rows) > 10000:
            raise ValueError("Too many prediction records")
    return rows


def native_content(bundle, *, run_id, model_abbr, dataset, sample_id, attempt):
    if bundle.get("run_id") != str(run_id):
        raise ValueError("Native archive belongs to another run")
    matches = []
    for entry in bundle.get("files", []):
        path = PurePosixPath(entry["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe native evidence path")
        if not str(path).endswith(f"/predictions/{model_abbr}/{dataset}.jsonl"):
            continue
        content = entry["content"]
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != entry["sha256"]:
            raise ValueError("Native prediction checksum mismatch")
        for row in prediction_records(content):
            if row.get("data_abbr") != dataset or str(row.get("id")) != sample_id:
                continue
            # No positional matching or assigning one response to a later retry.
            if row.get("attempt", 1) != attempt:
                continue
            messages = row.get("origin_prompt")
            if not isinstance(messages, list) or not isinstance(row.get("prediction"), str):
                continue
            if not all(
                isinstance(message, dict) and isinstance(message.get("prompt"), str)
                for message in messages
            ):
                raise ValueError("Invalid native prompt structure")
            matches.append(
                {
                    "prompt": "\n\n".join(message["prompt"] for message in messages),
                    "response": row["prediction"],
                    "messages": messages,
                    "native_evidence": {
                        "path": str(path),
                        "sha256": entry["sha256"],
                        "record_id": str(row["id"]),
                        "record_uuid": row.get("uuid"),
                        "source": "aisbench_native_prediction",
                    },
                }
            )
    if len(matches) > 1:
        raise ValueError("Ambiguous native case evidence")
    return matches[0] if matches else None


async def enrich_case(session, settings, row, original):
    import asyncio

    from sqlalchemy import select

    from autoeval.datasets import read_manifest
    from autoeval.models import RunSnapshot
    from autoeval.unified_artifacts import UnifiedArtifact

    if original.get("schema_version") != "unified-case.v1" or original.get("prompt") is not None:
        return original
    snapshot = await session.scalar(select(RunSnapshot).where(RunSnapshot.run_id == row.run_id))
    if snapshot and snapshot.canonical_body.get("schema_version") == "planned-run.v1":
        from autoeval.native_predictions import selected
        from autoeval.orchestration import DatasetExecution
        from autoeval.planning_observations import case_contract

        children = list(
            await session.scalars(
                select(DatasetExecution).where(DatasetExecution.run_id == row.run_id)
            )
        )
        matching = [
            c
            for c in children
            if c.payload["dataset"] == row.dataset_key
            and any(s["sample_id"] == row.sample_id for s in c.payload["samples"])
        ]
        if len(matching) != 1 or row.attempt_no != 1:
            return original
        child = matching[0]
        artifact = await session.scalar(
            select(UnifiedArtifact).where(
                UnifiedArtifact.run_id == row.run_id,
                UnifiedArtifact.collection_key == "planning-native:" + str(child.id),
            )
        )
        if artifact is None:
            return original
        bundle = await asyncio.to_thread(read_manifest, settings, artifact)
        contract = case_contract(child.payload)
        if (
            bundle.get("run_id") != str(row.run_id)
            or bundle.get("child_id") != str(child.id)
            or bundle.get("contract") != contract
        ):
            raise ValueError("Native archive selection identity mismatch")
        case_id = next(k for k, v in contract["sample_ids"].items() if v == row.sample_id)
        found = selected(bundle["files"], contract).get(case_id)
        if found is None:
            return original
        native, file = found
        messages = native.get("origin_prompt")
        if not isinstance(messages, list) or not all(
            isinstance(m, dict) and isinstance(m.get("prompt"), str) for m in messages
        ):
            raise ValueError("Invalid native prompt structure")
        return {
            **original,
            "prompt": "\n\n".join(m["prompt"] for m in messages),
            "response": native["prediction"],
            "messages": messages,
            "native_evidence": {
                "path": file["path"],
                "sha256": file["sha256"],
                "record_id": case_id,
                "record_uuid": native.get("uuid"),
                "source": "aisbench_native_prediction",
            },
            "evidence_sources": {
                "case_sha256": row.sha256,
                "native_archive_sha256": artifact.sha256,
                "enrichment": "read_time_from_verified_native_archive",
            },
        }
    artifact = await session.scalar(
        select(UnifiedArtifact).where(
            UnifiedArtifact.run_id == row.run_id, UnifiedArtifact.collection_key == "cli-native-v1"
        )
    )
    if artifact is None:
        return original
    if not snapshot or snapshot.canonical_body.get("execution_path") != "aisbench_cli_monitor":
        return original
    bundle = await asyncio.to_thread(read_manifest, settings, artifact)
    content = native_content(
        bundle,
        run_id=row.run_id,
        model_abbr=snapshot.canonical_body["model_abbr"],
        dataset=row.dataset_key,
        sample_id=row.sample_id,
        attempt=row.attempt_no,
    )
    if content is None:
        return original
    return {
        **original,
        **content,
        "evidence_sources": {
            "case_sha256": row.sha256,
            "native_archive_sha256": artifact.sha256,
            "enrichment": "read_time_from_verified_native_archive",
        },
    }
