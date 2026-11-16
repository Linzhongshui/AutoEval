"""Compatibility alias: implementation moved to autoeval.infrastructure.db."""

import sys

from autoeval.infrastructure import db as _impl

sys.modules[__name__] = _impl
