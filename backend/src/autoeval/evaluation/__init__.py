"""Evaluation module package: ORM models and application services.

Import service members from ``autoeval.evaluation.service`` directly; keeping
this init limited to models avoids load-order cycles with flat modules that
still import ``autoeval.evaluations`` for the shared report ORM class.
"""

from autoeval.evaluation.models import CapacityLease, DatasetExecution, EvaluationReport

__all__ = [
    "CapacityLease",
    "DatasetExecution",
    "EvaluationReport",
]
