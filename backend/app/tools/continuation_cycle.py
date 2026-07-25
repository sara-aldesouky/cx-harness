"""Immutable provider-neutral record of one completed tool continuation cycle."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.tools.continuation_adapter import ProviderContinuationPayload
from app.tools.execution_outcome import ToolExecutionOutcome
from app.tools.execution_request import ToolExecutionRequest
from app.tools.immutable_json import json_copy
from app.tools.selection import ValidatedToolSelection


class ToolContinuationCycleError(ValueError):
    """Base error for completed-cycle contract construction failures."""


class InvalidToolContinuationCycleInputError(ToolContinuationCycleError):
    """Raised when a required artifact does not use its established contract."""


class ToolContinuationCycleCorrelationError(ToolContinuationCycleError):
    """Raised when call IDs do not correlate across lifecycle artifacts."""


class ToolContinuationCycleIdentityMismatchError(ToolContinuationCycleError):
    """Raised when canonical tool name or version changes across artifacts."""


class ToolContinuationCycleProviderMismatchError(ToolContinuationCycleError):
    """Raised when the continuation payload belongs to another provider."""


class ToolContinuationCycleArtifactMismatchError(ToolContinuationCycleError):
    """Raised when selection and request arguments are inconsistent."""


class ToolContinuationCycle(BaseModel):
    """One immutable set of already-produced, correlated lifecycle artifacts.

    This contract represents completed state only. It performs no selection,
    execution, translation, provider invocation, or persistence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    provider_name: str
    selection: ValidatedToolSelection
    execution_request: ToolExecutionRequest
    execution_outcome: ToolExecutionOutcome
    continuation_payload: ProviderContinuationPayload


class ToolContinuationCycleFactory:
    """Verify consistency among artifacts without recreating any lifecycle stage."""

    def create(
        self,
        provider_name: str,
        selection: ValidatedToolSelection,
        execution_request: ToolExecutionRequest,
        execution_outcome: ToolExecutionOutcome,
        continuation_payload: ProviderContinuationPayload,
    ) -> ToolContinuationCycle:
        """Return one completed cycle after provider-neutral invariant checks."""

        normalized_provider = self._normalize_provider(provider_name)
        self._require_contract(
            selection, ValidatedToolSelection, "selection"
        )
        self._require_contract(
            execution_request, ToolExecutionRequest, "execution_request"
        )
        self._require_contract(
            execution_outcome, ToolExecutionOutcome, "execution_outcome"
        )
        self._require_contract(
            continuation_payload,
            ProviderContinuationPayload,
            "continuation_payload",
        )

        call_ids = (
            selection.call_id,
            execution_request.call_id,
            execution_outcome.call_id,
            continuation_payload.call_id,
        )
        if len(set(call_ids)) != 1:
            raise ToolContinuationCycleCorrelationError(
                "tool continuation artifacts have inconsistent call IDs"
            )

        tool_names = (
            selection.tool_name,
            execution_request.tool_name,
            execution_outcome.tool_name,
        )
        if len(set(tool_names)) != 1:
            raise ToolContinuationCycleIdentityMismatchError(
                "tool continuation artifacts have inconsistent tool names for "
                f"call ID {selection.call_id!r}"
            )

        tool_versions = (
            selection.tool_version,
            execution_request.tool_version,
            execution_outcome.tool_version,
        )
        if len(set(tool_versions)) != 1:
            raise ToolContinuationCycleIdentityMismatchError(
                "tool continuation artifacts have inconsistent tool versions for "
                f"call ID {selection.call_id!r}"
            )

        if json_copy(selection.arguments) != json_copy(execution_request.arguments):
            raise ToolContinuationCycleArtifactMismatchError(
                "selection and execution request arguments differ for "
                f"tool {selection.tool_name!r} version {selection.tool_version!r} "
                f"and call ID {selection.call_id!r}"
            )

        if continuation_payload.provider_name != normalized_provider:
            raise ToolContinuationCycleProviderMismatchError(
                "continuation payload provider does not match provider "
                f"{normalized_provider!r} for call ID {selection.call_id!r}"
            )

        return ToolContinuationCycle(
            provider_name=normalized_provider,
            selection=selection,
            execution_request=execution_request,
            execution_outcome=execution_outcome,
            continuation_payload=continuation_payload,
        )

    @staticmethod
    def _normalize_provider(provider_name: object) -> str:
        if not isinstance(provider_name, str):
            raise InvalidToolContinuationCycleInputError(
                "provider_name must be a string"
            )
        normalized = provider_name.strip().lower()
        if not normalized:
            raise InvalidToolContinuationCycleInputError(
                "provider_name must not be empty or whitespace"
            )
        return normalized

    @staticmethod
    def _require_contract(value: object, expected: type, field_name: str) -> None:
        if not isinstance(value, expected):
            raise InvalidToolContinuationCycleInputError(
                f"{field_name} must use the {expected.__name__} contract"
            )
