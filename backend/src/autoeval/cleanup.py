"""Compatibility alias: implementation moved to autoeval.infrastructure.cleanup."""

import sys

from autoeval.infrastructure import cleanup as _impl

sys.modules[__name__] = _impl
