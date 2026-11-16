"""Compatibility alias: implementation moved to autoeval.infrastructure.domain."""

import sys

from autoeval.infrastructure import domain as _impl

sys.modules[__name__] = _impl
