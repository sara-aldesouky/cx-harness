"""Lazy public exports for deterministic Stage 13.2 entity resolution."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "EntityMention": "app.entity_resolution.contracts",
    "EntityResolutionRequest": "app.entity_resolution.contracts",
    "EntityResolutionResult": "app.entity_resolution.contracts",
    "ResolutionCandidate": "app.entity_resolution.contracts",
    "ResolvedEntity": "app.entity_resolution.contracts",
    "ResolutionRequirement": "app.entity_resolution.contracts",
    "ResolutionStatus": "app.entity_resolution.contracts",
    "OrderMentionExtractor": "app.entity_resolution.mention_extractor",
    "ExistingOrderRepositoryAdapter": "app.entity_resolution.order_repository",
    "OrderResolutionRecord": "app.entity_resolution.order_repository",
    "OrderResolutionRepository": "app.entity_resolution.order_repository",
    "OrderEntityResolver": "app.entity_resolution.order_resolver",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
