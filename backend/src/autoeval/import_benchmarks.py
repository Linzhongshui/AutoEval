"""Compatibility exports; implementation moved to autoeval.catalog.

``python -m autoeval.import_benchmarks`` stays the documented CLI entry."""

from autoeval.catalog.import_benchmarks import (
    CONTENT_FIELDS,
    BaselineBundle,
    BaselineConflictError,
    BaselineInput,
    import_baselines,
    main,
)

__all__ = [
    "CONTENT_FIELDS",
    "BaselineBundle",
    "BaselineConflictError",
    "BaselineInput",
    "import_baselines",
    "main",
]

if __name__ == "__main__":
    main()
