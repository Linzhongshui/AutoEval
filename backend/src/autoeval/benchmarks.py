"""Compatibility exports; implementation moved to autoeval.catalog."""

from autoeval.catalog.benchmarks import (
    REQUIRED_CONDITIONS,
    compare_baseline,
)
from autoeval.catalog.models import BenchmarkBaseline

__all__ = [
    "REQUIRED_CONDITIONS",
    "BenchmarkBaseline",
    "compare_baseline",
]
