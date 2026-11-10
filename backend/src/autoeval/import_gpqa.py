"""Operator data import: full native load, object bundle, deterministic Lite manifest."""

import argparse
import asyncio
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

from autoeval.api import create_app
from autoeval.config import get_settings
from autoeval.datasets import canonical_manifest, write_manifest
from autoeval.native_smoke import invoke
from autoeval.registry import AssetVersion
from autoeval.resources import ResourceBinding, inspect_executor


async def import_dataset(csv_path, source_path, resource_id, lite_count):
    settings = get_settings()
    source = json.loads(source_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if digest != source["csv_sha256"]:
        raise ValueError("CSV differs from recorded provenance")
    if not 1 <= lite_count <= 100:
        raise ValueError("Lite import count must be between 1 and 100")
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://import") as api,
    ):
        async with app.state.sessions() as session:
            resource = await session.get(ResourceBinding, resource_id)
            if resource is None:
                raise ValueError("Resource not found")
        identity = await asyncio.to_thread(
            inspect_executor, settings.docker_executable, resource.container_id
        )
        if not identity["running"] or identity["image_id"] != resource.image_id:
            raise ValueError("Executor identity changed")
        remote_path = f"/work/tools/aisbench/import-{digest}.csv"
        await asyncio.to_thread(
            subprocess.run,
            [
                settings.docker_executable,
                "cp",
                str(csv_path.resolve()),
                f"{resource.container_id}:{remote_path}",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
        native = await asyncio.to_thread(
            invoke,
            settings,
            resource.container_id,
            {"operation": "prepare_gpqa_diamond", "csv_path": remote_path},
        )
        if native["source_sha256"] != digest:
            raise ValueError("Executor input checksum mismatch")
        if len(native["samples"]) < lite_count:
            raise ValueError("Lite exceeds full sample count")
        raw = canonical_manifest({"schema_version": "native-dataset.v1", **native})
        bundle_digest = hashlib.sha256(raw).hexdigest()
        object_key = f"dataset-bundles/{bundle_digest}.json"
        await asyncio.to_thread(write_manifest, settings, object_key, raw)
        version_label = f"{digest[:16]}-{native['tool_revision'][:12]}"
        body = {
            "dataset_key": "gpqa-diamond",
            "name": "GPQA Diamond",
            "version": version_label,
            "manifest_key": "full",
            "scope": "full",
            "samples": [
                {"sample_id": row["sample_id"], "sha256": row["sha256"]}
                for row in native["samples"]
            ],
        }
        prefix = "/api/autoeval/v1/dataset-manifests"
        response = await api.post(prefix, json=body)
        if response.status_code != 201:
            raise ValueError("Full manifest registration failed")
        full = response.json()["data"]
        metadata = {
            "schema_version": "dataset-content.v1",
            "object_key": object_key,
            "sha256": bundle_digest,
            "source": source,
            "tool_revision": native["tool_revision"],
            "sample_count": len(native["samples"]),
            "approval_status": "not_approved",
        }
        async with app.state.sessions() as session, session.begin():
            version = await session.scalar(
                select(AssetVersion)
                .where(AssetVersion.id == uuid.UUID(full["dataset_version_id"]))
                .with_for_update()
            )
            if version.metadata_json and version.metadata_json != metadata:
                raise ValueError("Dataset version content is immutable")
            version.metadata_json = metadata
        lite_response = await api.post(
            prefix,
            json={
                **body,
                "manifest_key": f"lite-first-{lite_count}",
                "scope": "lite",
                "parent_id": full["id"],
                "samples": body["samples"][:lite_count],
            },
        )
        if lite_response.status_code != 201:
            raise ValueError("Lite manifest registration failed")
        lite = lite_response.json()["data"]
        return {
            "dataset_version_id": full["dataset_version_id"],
            "version": version_label,
            "full_manifest_id": full["id"],
            "full_count": full["sample_count"],
            "lite_manifest_id": lite["id"],
            "lite_count": lite["sample_count"],
            "source_csv_sha256": digest,
            "bundle_sha256": bundle_digest,
            "approval_status": "not_approved",
            "model_calls": 0,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Import GPQA using the pinned native loader; sends no model requests"
    )
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--resource-id", type=uuid.UUID, required=True)
    parser.add_argument("--lite-count", type=int, default=5)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(import_dataset(args.csv, args.source, args.resource_id, args.lite_count))
        )
    )


if __name__ == "__main__":
    main()
