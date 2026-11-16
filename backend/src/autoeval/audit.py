"""Compatibility alias: implementation moved to autoeval.infrastructure.audit."""

import sys

from autoeval.infrastructure import audit as _impl

sys.modules[__name__] = _impl
