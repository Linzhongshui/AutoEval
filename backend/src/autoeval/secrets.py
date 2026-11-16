"""Compatibility alias: implementation moved to autoeval.infrastructure.secrets."""

import sys

from autoeval.infrastructure import secrets as _impl

sys.modules[__name__] = _impl
