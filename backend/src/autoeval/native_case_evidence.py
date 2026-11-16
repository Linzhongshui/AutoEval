"""Compatibility exports; implementation moved to autoeval.reporting."""

from autoeval.reporting.native_case_evidence import (
    enrich_case,
    native_content,
    prediction_records,
)

__all__ = ["enrich_case", "native_content", "prediction_records"]
