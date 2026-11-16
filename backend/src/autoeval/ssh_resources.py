"""Compatibility exports; implementation moved to autoeval.resources."""

from autoeval.resources.models import SSHResourceBinding
from autoeval.resources.ssh_resources import (
    SSHCredential,
    SSHResourceInput,
    connection_for,
    list_resources,
    register,
    resource_data,
    router,
    save_credential,
    validate,
)

__all__ = [
    "SSHCredential",
    "SSHResourceBinding",
    "SSHResourceInput",
    "connection_for",
    "list_resources",
    "register",
    "resource_data",
    "router",
    "save_credential",
    "validate",
]
