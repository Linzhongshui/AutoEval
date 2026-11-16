"""Catalog module package: models, manifests, registry, profiles, configurations
and baselines. ``autoeval.standard_inputs`` stays at the top level while its
companion import CLI lives here; see docs/refactor-inventory.md."""

from autoeval.catalog import models  # noqa: F401 -- registers ORM metadata
