"""Compatibility exports; implementation moved to autoeval.catalog.

``python -m autoeval.import_standard_inputs`` stays the documented CLI entry."""

from autoeval.catalog.import_standard_inputs import main, read_directory

__all__ = ["main", "read_directory"]

if __name__ == "__main__":
    main()
