"""Compatibility exports; implementation moved to autoeval.catalog."""

from autoeval.catalog.models import ConfigDatasetBinding, EvaluationProfile
from autoeval.catalog.profiles import (
    ProfileInput,
    ToolContract,
    list_profiles,
    profile_data,
    register_profile,
    router,
)

__all__ = [
    "ConfigDatasetBinding",
    "EvaluationProfile",
    "ProfileInput",
    "ToolContract",
    "list_profiles",
    "profile_data",
    "register_profile",
    "router",
]
