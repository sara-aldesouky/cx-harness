"""Composition root for the single tool-continuation runtime graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from app.tools.continuation_adapter_registry import (
    ProviderContinuationAdapterRegistry,
)
from app.tools.continuation_cycle import ToolContinuationCycleFactory
from app.tools.continuation_cycle_service import (
    SingleToolContinuationCycleService,
)
from app.tools.continuation_service import ProviderContinuationService
from app.tools.execution_gateway import SingleToolExecutionGateway
from app.tools.execution_outcome import ToolExecutionOutcomeFactory
from app.tools.execution_request import ToolExecutionRequestFactory
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from app.authorization import ToolAuthorizationService
    from app.role_policy import ToolRolePolicyService
    from app.tool_authorization import RequestedToolAuthorizationService


class ToolContinuationRuntimeCompositionError(RuntimeError):
    """Base error for tool-continuation dependency composition failures."""


class InvalidToolContinuationRuntimeDependencyError(
    ToolContinuationRuntimeCompositionError, TypeError
):
    """Raised when a required externally owned dependency is invalid."""


class ToolContinuationRuntimeConstructionError(
    ToolContinuationRuntimeCompositionError
):
    """Raised when one internal application component cannot be constructed."""


@dataclass(frozen=True)
class ToolContinuationRuntime:
    """Immutable public container for one independently composed runtime graph."""

    cycle_service: SingleToolContinuationCycleService


def build_tool_continuation_runtime(
    *,
    tool_registry: ToolRegistry,
    continuation_adapter_registry: ProviderContinuationAdapterRegistry,
    audit_repository: Any,
    audit_payload_max_bytes: int = 16_384,
    authorization_service: ToolAuthorizationService | None = None,
    role_policy_service: ToolRolePolicyService | None = None,
    tool_authorization_service: RequestedToolAuthorizationService | None = None,
    tool_factory: Callable[[type], Any] | None = None,
    completion_observer: Callable[..., None] | None = None,
) -> ToolContinuationRuntime:
    """Compose one ready runtime without lookup, execution, registration, or I/O."""

    if not isinstance(tool_registry, ToolRegistry):
        raise InvalidToolContinuationRuntimeDependencyError(
            "tool_registry must be a ToolRegistry"
        )
    if not isinstance(
        continuation_adapter_registry, ProviderContinuationAdapterRegistry
    ):
        raise InvalidToolContinuationRuntimeDependencyError(
            "continuation_adapter_registry must be a "
            "ProviderContinuationAdapterRegistry"
        )
    if not _is_audit_repository(audit_repository):
        raise InvalidToolContinuationRuntimeDependencyError(
            "audit_repository must implement create_running() and finalize()"
        )
    if (
        not isinstance(audit_payload_max_bytes, int)
        or isinstance(audit_payload_max_bytes, bool)
        or audit_payload_max_bytes <= 0
    ):
        raise InvalidToolContinuationRuntimeDependencyError(
            "audit_payload_max_bytes must be a positive integer"
        )

    try:
        executor = ToolExecutor(
            tool_registry,
            audit_repository,
            audit_payload_max_bytes=audit_payload_max_bytes,
            tool_factory=tool_factory,
        )
    except Exception as error:
        raise ToolContinuationRuntimeConstructionError(
            "failed to construct tool_executor"
        ) from error

    try:
        execution_gateway = SingleToolExecutionGateway(
            tool_registry,
            executor,
            authorization_service=authorization_service,
            role_policy_service=role_policy_service,
            tool_authorization_service=tool_authorization_service,
        )
    except Exception as error:
        raise ToolContinuationRuntimeConstructionError(
            "failed to construct execution_gateway"
        ) from error

    try:
        continuation_service = ProviderContinuationService(
            continuation_adapter_registry
        )
    except Exception as error:
        raise ToolContinuationRuntimeConstructionError(
            "failed to construct continuation_service"
        ) from error

    try:
        cycle_service = SingleToolContinuationCycleService(
            ToolExecutionRequestFactory(),
            execution_gateway,
            ToolExecutionOutcomeFactory(),
            continuation_service,
            ToolContinuationCycleFactory(),
            completion_observer=completion_observer,
        )
    except Exception as error:
        raise ToolContinuationRuntimeConstructionError(
            "failed to construct cycle_service"
        ) from error

    return ToolContinuationRuntime(cycle_service=cycle_service)


def _is_audit_repository(value: object) -> bool:
    """Validate the existing executor audit lifecycle structurally without calls."""

    return callable(getattr(value, "create_running", None)) and callable(
        getattr(value, "finalize", None)
    )
