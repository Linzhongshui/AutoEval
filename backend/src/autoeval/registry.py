"""Compatibility exports; implementation moved to autoeval.catalog."""

from autoeval.catalog.registry import (
    Asset,
    AssetVersion,
    CatalogRegistration,
    DefaultConfig,
    ModelConfigBinding,
    ModelCreate,
    get_default,
    list_models,
    model_versions,
    register_catalog_model,
    register_model,
    router,
    set_default,
)

__all__ = [
    "Asset",
    "AssetVersion",
    "CatalogRegistration",
    "DefaultConfig",
    "ModelConfigBinding",
    "ModelCreate",
    "get_default",
    "list_models",
    "model_versions",
    "register_catalog_model",
    "register_model",
    "router",
    "set_default",
]
