"""Application boundary for exactly one raw provider tool-call cycle."""

from __future__ import annotations

from app.tools.context import ExecutionContext
from app.tools.continuation_adapter import ProviderContinuationPayload
from app.tools.continuation_cycle import ToolContinuationCycle
from app.tools.execution_outcome import ToolExecutionOutcome
from app.tools.execution_request import ToolExecutionRequest
from app.tools.selection import ToolSelectionRequest, ValidatedToolSelection
from app.tools.selection_service import ToolSelectionService
from app.tools.tool_runtime import ToolContinuationRuntime


class SingleProviderToolCallCycleServiceError(Exception):
    """Base error for the single provider-call application boundary."""


class InvalidProviderToolCallCycleInputError(
    SingleProviderToolCallCycleServiceError, TypeError
):
    """Raised when service inputs do not represent one raw provider call."""


class ProviderToolCallSelectionError(SingleProviderToolCallCycleServiceError):
    """Raised when provider translation or tool selection fails."""


class InvalidProviderToolCallSelectionCountError(
    SingleProviderToolCallCycleServiceError
):
    """Raised unless selection produces exactly one validated tool call."""


class ProviderToolCallCycleExecutionError(
    SingleProviderToolCallCycleServiceError
):
    """Raised when the composed execution-to-continuation runtime fails."""


class InvalidProviderToolCallCycleResultError(
    SingleProviderToolCallCycleServiceError
):
    """Raised when the runtime violates its completed-cycle contract."""


class SingleProviderToolCallCycleService:
    """Join raw provider-call selection to one composed continuation cycle.

    Provider translation and validation remain owned by ``ToolSelectionService``.
    Execution, auditing, outcome translation, and cycle construction remain owned
    by the supplied ``ToolContinuationRuntime`` graph.
    """

    def __init__(
        self,
        selection_service: ToolSelectionService,
        runtime: ToolContinuationRuntime,
    ) -> None:
        if not isinstance(selection_service, ToolSelectionService):
            raise TypeError("selection_service must be a ToolSelectionService")
        if not isinstance(runtime, ToolContinuationRuntime):
            raise TypeError("runtime must be a ToolContinuationRuntime")
        self._selection_service = selection_service
        self._runtime = runtime

    def run(
        self,
        provider_name: str,
        provider_payload: object,
        context: ExecutionContext,
    ) -> ToolContinuationCycle:
        """Select and execute exactly one provider-requested tool without retry."""

        if not isinstance(provider_name, str) or not provider_name.strip():
            raise InvalidProviderToolCallCycleInputError(
                "provider_name must be a non-empty string"
            )
        if not isinstance(context, ExecutionContext):
            raise InvalidProviderToolCallCycleInputError(
                "context must be a trusted ExecutionContext"
            )
        invalid_payload_contracts = (
            ToolSelectionRequest,
            ValidatedToolSelection,
            ToolExecutionRequest,
            ToolExecutionOutcome,
            ProviderContinuationPayload,
            ToolContinuationCycle,
        )
        if (
            provider_payload is None
            or isinstance(provider_payload, (list, tuple))
            or isinstance(provider_payload, invalid_payload_contracts)
        ):
            raise InvalidProviderToolCallCycleInputError(
                "provider_payload must represent one raw provider response"
            )

        safe_provider = provider_name.strip().lower()
        try:
            selections = self._selection_service.select(
                provider_name, provider_payload
            )
        except Exception as error:
            raise ProviderToolCallSelectionError(
                f"tool selection failed for provider {safe_provider!r}"
            ) from error

        if not isinstance(selections, tuple) or len(selections) != 1:
            count = len(selections) if isinstance(selections, tuple) else "invalid"
            raise InvalidProviderToolCallSelectionCountError(
                "provider tool-call selection must produce exactly one selection "
                f"for provider {safe_provider!r}; received {count}"
            )
        selection = selections[0]
        if not isinstance(selection, ValidatedToolSelection):
            raise ProviderToolCallSelectionError(
                "tool selection returned an invalid artifact for "
                f"provider {safe_provider!r}"
            )

        try:
            cycle = self._runtime.cycle_service.run(
                provider_name, selection, context
            )
        except Exception as error:
            raise ProviderToolCallCycleExecutionError(
                f"tool continuation cycle failed for provider {safe_provider!r} "
                f"and call ID {selection.call_id!r}"
            ) from error

        if not isinstance(cycle, ToolContinuationCycle):
            raise InvalidProviderToolCallCycleResultError(
                "tool continuation runtime returned an invalid result for "
                f"provider {safe_provider!r} and call ID {selection.call_id!r}"
            )
        if cycle.provider_name != safe_provider:
            raise InvalidProviderToolCallCycleResultError(
                "tool continuation runtime returned a provider-mismatched cycle "
                f"for provider {safe_provider!r} and call ID {selection.call_id!r}"
            )
        return cycle
