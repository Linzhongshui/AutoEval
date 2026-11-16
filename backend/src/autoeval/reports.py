"""Compatibility exports; implementation moved to autoeval.reporting."""

from autoeval.reporting.reports import (
    ReportView,
    catalog,
    detail,
    evidence,
    report_data,
    router,
)

__all__ = [
    "ReportView",
    "catalog",
    "detail",
    "evidence",
    "report_data",
    "router",
]
