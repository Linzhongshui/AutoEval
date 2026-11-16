"""Compatibility exports; implementation moved to autoeval.catalog."""

from autoeval.catalog.adaptor_versions import (
    CURRENT_ADAPTOR,
    LEGACY_ADAPTOR,
    RUNTIME_FIELDS,
    STANDARD_REVISION,
    separate_runtime,
)

__all__ = [
    "CURRENT_ADAPTOR",
    "LEGACY_ADAPTOR",
    "RUNTIME_FIELDS",
    "STANDARD_REVISION",
    "separate_runtime",
]
