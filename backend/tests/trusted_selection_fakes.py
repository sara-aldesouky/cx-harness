"""Test-only composition helpers for the mandatory Stage 13.4 boundary."""

from app.argument_binding import TrustedArgumentBinder
from app.services.trusted_argument_binding_runtime import (
    TrustedSelectionPipeline,
    build_runtime_binding_policy_registry,
)
from app.tools.registry import ToolRegistry
from app.tools.selection import ToolSelectionResolver


class UnexpectedOrderResolver:
    def resolve(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("an unprotected test tool must not resolve an order")


def trusted_selection_pipeline(registry: ToolRegistry) -> TrustedSelectionPipeline:
    policies = build_runtime_binding_policy_registry(registry)
    return TrustedSelectionPipeline(
        TrustedArgumentBinder(
            policies,
            UnexpectedOrderResolver(),
            known_tool_names=(tool.metadata.name for tool in registry.list()),
        ),
        ToolSelectionResolver(registry),
    )
