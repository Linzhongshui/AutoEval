"""Compatibility alias: implementation moved to autoeval.analysis.trial_analysis_schema."""

import sys

from autoeval.analysis import trial_analysis_schema as _impl

sys.modules[__name__] = _impl
