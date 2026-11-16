"""Compatibility alias: implementation moved to autoeval.infrastructure.contracts."""

import sys

from autoeval.infrastructure import contracts as _impl

sys.modules[__name__] = _impl
