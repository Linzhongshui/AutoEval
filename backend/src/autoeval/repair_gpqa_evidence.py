"""Restore reproducible dataset objects only when existing DB digests match exactly.

Never reconstruct model outputs, reports, scores, or database history.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

from botocore.exceptions import ClientError
from sqlalchemy import select

from autoeval.config import get_settings
from autoeval.datasets import DatasetManifest, canonical_manifest, storage
from autoeval.db import create_database
from autoeval.models import RunSnapshot
from autoeval.native_smoke import invoke
from autoeval.registry import Asset, AssetVersion
from autoeval.resources import ResourceBinding, inspect_executor


def restore_exact(client, bucket, key, expected, raw, *, apply=False):
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Reconstructed object differs from immutable digest")
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
            raise
    else:
        try:
            existing = response["Body"].read(16 * 1024 * 1024 + 1)
        finally:
            response["Body"].close()
        if hashlib.sha256(existing).hexdigest() != expected:
            raise ValueError("Existing object differs; refusing to overwrite")
        return "verified"
    if apply:
        client.put_object(Bucket=bucket, Key=key, Body=raw, ContentType="application/json")
    return "restored" if apply else "would_restore"


async def repair(csv_path, provenance, resource_id, *, apply=False):
    settings = get_settings()
    source = json.loads(provenance.read_text(encoding="utf-8"))
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if digest != source["csv_sha256"]:
        raise ValueError("CSV does not match approved source provenance")
    engine, sessions = create_database(settings)
    client = storage(settings)
    try:
        async with sessions() as session:
            resource = await session.get(ResourceBinding, resource_id)
            if resource is None:
                raise ValueError("Registered executor required")
            versions = list(
                await session.scalars(
                    select(AssetVersion)
                    .join(Asset, Asset.id == AssetVersion.asset_id)
                    .where(Asset.asset_key == "gpqa-diamond")
                )
            )
            snapshots = list(await session.scalars(select(RunSnapshot)))
        identity = await asyncio.to_thread(
            inspect_executor, settings.docker_executable, resource.container_id
        )
        if not identity["running"] or identity["image_id"] != resource.image_id:
            raise ValueError("Executor identity changed")
        remote = f"/work/tools/aisbench/repair-{digest}.csv"
        await asyncio.to_thread(
            subprocess.run,
            [
                settings.docker_executable,
                "cp",
                str(csv_path.resolve()),
                f"{resource.container_id}:{remote}",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
        native = await asyncio.to_thread(
            invoke,
            settings,
            resource.container_id,
            {"operation": "prepare_gpqa_diamond", "csv_path": remote},
        )
        if native["source_sha256"] != digest:
            raise ValueError("Native source identity changed")
        raw_bundle = canonical_manifest({"schema_version": "native-dataset.v1", **native})
        refs = [{"sample_id": s["sample_id"], "sha256": s["sha256"]} for s in native["samples"]]
        outcomes = []
        for version in versions:
            metadata = version.metadata_json
            if metadata.get("sha256") != hashlib.sha256(raw_bundle).hexdigest():
                continue
            outcomes.append(
                restore_exact(
                    client,
                    settings.s3_bucket,
                    metadata["object_key"],
                    metadata["sha256"],
                    raw_bundle,
                    apply=apply,
                )
            )
            async with sessions() as session:
                manifests = list(
                    await session.scalars(
                        select(DatasetManifest).where(
                            DatasetManifest.dataset_version_id == version.id
                        )
                    )
                )
            for manifest in manifests:
                samples = refs if manifest.scope == "full" else None
                for snapshot in snapshots:
                    body = snapshot.canonical_body
                    if body.get("manifest_id") == str(manifest.id):
                        samples = body["samples"]
                        break
                if (
                    samples is None
                    and manifest.manifest_key == f"lite-first-{manifest.sample_count}"
                ):
                    samples = refs[: manifest.sample_count]
                if samples is None:
                    outcomes.append("unrecoverable_manifest")
                    continue
                raw = canonical_manifest(
                    {
                        "dataset_key": "gpqa-diamond",
                        "name": "GPQA Diamond",
                        "version": version.version,
                        "manifest_key": manifest.manifest_key,
                        "scope": manifest.scope,
                        "parent_id": str(manifest.parent_id) if manifest.parent_id else None,
                        "samples": samples,
                    }
                )
                outcomes.append(
                    restore_exact(
                        client,
                        settings.s3_bucket,
                        manifest.object_key,
                        manifest.sha256,
                        raw,
                        apply=apply,
                    )
                )
        return {
            "objects": len(outcomes),
            "outcomes": outcomes,
            "reports_modified": 0,
            "model_calls": 0,
        }
    finally:
        client.close()
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--resource-id", type=uuid.UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(asyncio.run(repair(args.csv, args.source, args.resource_id, apply=args.apply)))
    )


if __name__ == "__main__":
    main()
