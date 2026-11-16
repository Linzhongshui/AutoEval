"""Compatibility exports; implementation moved to autoeval.catalog."""

from autoeval.catalog.datasets import (
    DatasetManifest,
    ManifestInput,
    SampleRef,
    canonical_manifest,
    list_manifests,
    manifest_detail,
    read_manifest,
    register,
    router,
    storage,
    summary,
    write_manifest,
)

__all__ = [
    "DatasetManifest",
    "ManifestInput",
    "SampleRef",
    "canonical_manifest",
    "list_manifests",
    "manifest_detail",
    "read_manifest",
    "register",
    "router",
    "storage",
    "summary",
    "write_manifest",
]
