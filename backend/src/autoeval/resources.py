"""Compatibility exports; implementation moved to autoeval.resources."""

from autoeval.resources.docker_bindings import (
    RegisterExecutor,
    inspect_executor,
    list_resources,
    register_executor,
    router,
    validate_resource,
)
from autoeval.resources.models import ResourceBinding, ResourceProvider

__all__ = [
    "RegisterExecutor",
    "ResourceBinding",
    "ResourceProvider",
    "inspect_executor",
    "list_resources",
    "register_executor",
    "router",
    "validate_resource",
]
