"""Compatibility exports; implementation moved to autoeval.catalog.

``python -m autoeval.import_standard_config`` stays the documented CLI entry."""

from autoeval.catalog.import_standard_config import (
    ImportConflict,
    StandardConfigInput,
    import_config,
    main,
    result_for,
    run_import,
)

__all__ = [
    "ImportConflict",
    "StandardConfigInput",
    "import_config",
    "main",
    "result_for",
    "run_import",
]

if __name__ == "__main__":
    main()
