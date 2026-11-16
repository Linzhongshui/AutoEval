"""Compatibility exports; implementation moved to autoeval.resources."""

from autoeval.resources.models import ConnectionProbe, TargetBinding
from autoeval.resources.targets import (
    CredentialInput,
    ServiceUpdate,
    TargetInput,
    check_connection,
    create_target,
    deduplicate_services,
    list_targets,
    probe_model_list,
    put_credential,
    router,
    update_service,
    validate_url,
)

__all__ = [
    "ConnectionProbe",
    "CredentialInput",
    "ServiceUpdate",
    "TargetBinding",
    "TargetInput",
    "check_connection",
    "create_target",
    "deduplicate_services",
    "list_targets",
    "probe_model_list",
    "put_credential",
    "router",
    "update_service",
    "validate_url",
]
