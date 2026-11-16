"""Compatibility exports; implementation moved to autoeval.resources."""

from autoeval.resources.execution_transport import (
    frozen_ssh_resource,
    ssh_transport,
)

__all__ = ["frozen_ssh_resource", "ssh_transport"]
