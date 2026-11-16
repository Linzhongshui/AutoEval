"""Compatibility exports; implementation moved to autoeval.reporting."""

from autoeval.reporting.export_trial import (
    EXCLUDED,
    OWNED,
    TEST,
    export,
    strings,
)

__all__ = [
    "EXCLUDED",
    "OWNED",
    "TEST",
    "export",
    "strings",
]

if __name__ == "__main__":
    import argparse
    import asyncio
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    asyncio.run(export(args.destination))
