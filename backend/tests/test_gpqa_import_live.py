"""Real public dataset import, no model calls and no benchmark scores."""

import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from autoeval.config import get_settings
from autoeval.datasets import read_manifest
from autoeval.db import create_database
from autoeval.import_gpqa import import_dataset
from autoeval.registry import AssetVersion
from autoeval.resources import ResourceBinding

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_GPQA_CSV"), reason="Pinned public data and native Docker tool required"
)


async def test_reimport_preserves_ids_and_bundle_matches_manifest():
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session:
            resource = await session.scalar(select(ResourceBinding).limit(1))
            assert resource
        csv = Path(os.environ["AE_GPQA_CSV"])
        result = await import_dataset(csv, csv.with_name("source.json"), resource.id, 5)
        assert result["full_count"] == 198
        assert result["lite_count"] == 5 and result["model_calls"] == 0
        async with sessions() as session:
            version = await session.get(AssetVersion, uuid.UUID(result["dataset_version_id"]))
            metadata = version.metadata_json
            assert metadata["approval_status"] == "not_approved"
        bundle = read_manifest(settings, SimpleNamespace(**metadata))
        assert len(bundle["samples"]) == 198
        assert bundle["source_sha256"] == result["source_csv_sha256"]
        assert len({s["sample_id"] for s in bundle["samples"]}) == 198
        # Query the exact immutable object, not a locally reconstructed CSV slice.
        from autoeval.datasets import DatasetManifest

        async with sessions() as session:
            lite = await session.get(DatasetManifest, uuid.UUID(result["lite_manifest_id"]))
        lite_data = read_manifest(settings, lite)
        assert lite_data["samples"] == [
            {"sample_id": row["sample_id"], "sha256": row["sha256"]}
            for row in bundle["samples"][:5]
        ]
    finally:
        await engine.dispose()
