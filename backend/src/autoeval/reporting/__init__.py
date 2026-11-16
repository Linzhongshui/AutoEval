"""Reporting module package: case history, unified outputs, reports, leaderboards
and the development data workbench. ``autoeval.reporting.export_trial`` is a
standalone CLI module and is deliberately not imported here to avoid loading
the API factory at package import time."""

from autoeval.reporting import models  # noqa: F401 -- registers ORM metadata
