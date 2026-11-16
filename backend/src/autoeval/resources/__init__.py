"""Resource module package: model-service targets, Docker and SSH bindings.

Transports resolve frozen credentials without leaking them into snapshots."""

from autoeval.resources.docker_bindings import (
    RegisterExecutor,
    inspect_executor,
    list_resources,
    register_executor,
    router,
    validate_resource,
)
from autoeval.resources.models import (
    ConnectionProbe,
    ResourceBinding,
    ResourceProvider,
    SSHResourceBinding,
    TargetBinding,
)

__all__ = [
    "ConnectionProbe",
    "RegisterExecutor",
    "ResourceBinding",
    "ResourceProvider",
    "SSHResourceBinding",
    "TargetBinding",
    "inspect_executor",
    "list_resources",
    "register_executor",
    "router",
    "validate_resource",
]
