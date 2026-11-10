import pytest
from pydantic import ValidationError

from autoeval.datasets import ManifestInput


def test_manifest_requires_unique_samples_and_parent():
    body = {
        "dataset_key": "demo",
        "name": "demo",
        "version": "v1",
        "manifest_key": "full",
        "scope": "full",
        "samples": [{"sample_id": "case-1", "sha256": "a" * 64}],
    }
    assert ManifestInput(**body).scope == "full"
    with pytest.raises(ValidationError):
        ManifestInput(**{**body, "samples": body["samples"] * 2})
    with pytest.raises(ValidationError):
        ManifestInput(**{**body, "scope": "lite"})
