"""Compatibility alias: implementation moved to autoeval.analysis.activity."""

import sys

from autoeval.analysis import activity as _impl

sys.modules[__name__] = _impl
