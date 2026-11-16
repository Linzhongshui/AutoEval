"""Compatibility alias: implementation moved to autoeval.infrastructure.config."""

import sys

from autoeval.infrastructure import config as _impl

sys.modules[__name__] = _impl
