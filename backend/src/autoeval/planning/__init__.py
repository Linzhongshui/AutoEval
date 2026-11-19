"""Compatibility exports for the planning package."""

from importlib import import_module

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


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name in {"PlanningArtifact", "PlanningJob"}:
        module = "autoeval.planning.models"
    elif name in {"CloseProbe", "envelope", "router"}:
        module = "autoeval.planning.routes"
    elif name in {"ApplyInput", "CurveInput", "PlanInput", "ProbeInput", "ResourceRef", "Strict", "TaskInput"}:
        module = "autoeval.planning.schemas"
    else:
        module = "autoeval.evaluation.service"
    return getattr(import_module(module), name)
