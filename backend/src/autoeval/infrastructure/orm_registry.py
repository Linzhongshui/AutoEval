"""Register every mapped table before reading Alembic target metadata."""

import autoeval.analysis.models
import autoeval.billing
import autoeval.catalog.models
import autoeval.evaluation.models
import autoeval.infrastructure.audit
import autoeval.infrastructure.cleanup
import autoeval.langfuse_integration
import autoeval.planning.models
import autoeval.reporting.models
import autoeval.resources.models
import autoeval.runs
import autoeval.standard_inputs
import autoeval.task_monitor  # noqa: F401
from autoeval.models import Base

target_metadata = Base.metadata
