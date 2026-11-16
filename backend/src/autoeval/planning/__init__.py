"""Planning module package; router stays here, shared evaluation input services
live in autoeval.evaluation.service and are re-exported for compatibility."""

from autoeval.evaluation.service import (
    artifact,
    current_preflight,
    manifest_dataset_matches,
    resolve_inputs,
    selection_identity,
    target_data,
)
from autoeval.planning.models import PlanningArtifact, PlanningJob
from autoeval.planning.routes import (
    ApplyInput,
    CloseProbe,
    CurveInput,
    PlanInput,
    ProbeInput,
    ResourceRef,
    Strict,
    TaskInput,
    envelope,
    router,
)

__all__ = [
    "ApplyInput",
    "CloseProbe",
    "CurveInput",
    "PlanInput",
    "PlanningArtifact",
    "PlanningJob",
    "ProbeInput",
    "ResourceRef",
    "Strict",
    "TaskInput",
    "artifact",
    "current_preflight",
    "envelope",
    "manifest_dataset_matches",
    "resolve_inputs",
    "router",
    "selection_identity",
    "target_data",
]
