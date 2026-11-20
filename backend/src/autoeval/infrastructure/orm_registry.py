"""Register every mapped table before reading Alembic target metadata."""

import autoeval.analysis.models
import autoeval.billing.models
import autoeval.catalog.models
import autoeval.catalog.standard_inputs
import autoeval.evaluation.models
import autoeval.evaluation.runs
import autoeval.evaluation.task_monitor
import autoeval.infrastructure.audit
import autoeval.infrastructure.cleanup
import autoeval.planning.models
import autoeval.reporting.langfuse_integration
import autoeval.reporting.models
import autoeval.resources.models  # noqa: F401
from autoeval.infrastructure.models import Base

target_metadata = Base.metadata
