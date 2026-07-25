"""Provider boundary for translating one completed outcome into continuation data."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_serializer,
    field_validator,
)
from pydantic_core import PydanticSerializationError

from app.tools.execution_outcome import ToolExecutionOutcome
from app.tools.immutable_json import freeze_json, json_copy
from app.tools.result import ToolError, ToolStatus


class ProviderContinuationAdapterError(ValueError):
    """Base error for provider continuation translation failures."""


class InvalidProviderContinuationOutcomeError(ProviderContinuationAdapterError):
    """Raised when an adapter does not receive ToolExecutionOutcome."""


class UnsupportedProviderContinuationStateError(ProviderContinuationAdapterError):
    """Raised when a malformed outcome bypassed its contract invariants."""


class ProviderContinuationSerializationError(ProviderContinuationAdapterError):
    """Raised when provider-specific continuation data cannot serialize safely."""


class ProviderContinuationPayload(BaseModel):
    """Immutable envelope around one adapter-owned provider payload."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    provider_name: str
    call_id: str
    payload: Mapping[str, Any]

    @field_validator("provider_name")
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("call_id")
    @classmethod
    def normalize_call_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("payload")
    @classmethod
    def validate_and_freeze_payload(
        cls, value: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if not value:
            raise ValueError("payload must not be empty")
        copied = json_copy(value)
        try:
            json.dumps(copied, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("payload must contain only JSON-compatible data") from error
        return freeze_json(copied)

    @field_serializer("payload")
    def serialize_payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)


class ProviderContinuationAdapter(ABC):
    """Translate a neutral outcome into one provider-owned continuation payload."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the stable provider identity supported by this adapter."""

        raise NotImplementedError

    @abstractmethod
    def translate(
        self, outcome: ToolExecutionOutcome
    ) -> ProviderContinuationPayload:
        """Translate exactly one completed outcome without calling a provider."""

        raise NotImplementedError


class MockProviderContinuationAdapter(ProviderContinuationAdapter):
    """Translate outcomes into the deterministic test-only mock protocol."""

    @property
    def provider_name(self) -> str:
        return "mock"

    def translate(
        self, outcome: ToolExecutionOutcome
    ) -> ProviderContinuationPayload:
        """Preserve correlation and status without prose or model invocation."""

        if not isinstance(outcome, ToolExecutionOutcome):
            raise InvalidProviderContinuationOutcomeError(
                "outcome must be a ToolExecutionOutcome"
            )

        if outcome.status is ToolStatus.SUCCESS:
            if outcome.output is None or outcome.error is not None:
                raise UnsupportedProviderContinuationStateError(
                    "tool outcome contains an unsupported success state"
                )
            provider_payload = {
                "type": "tool_result",
                "call_id": outcome.call_id,
                "tool": {
                    "name": outcome.tool_name,
                    "version": outcome.tool_version,
                },
                "status": outcome.status.value,
                "output": json_copy(outcome.output),
            }
        elif outcome.status is ToolStatus.FAILURE:
            if outcome.output is not None or not isinstance(outcome.error, ToolError):
                raise UnsupportedProviderContinuationStateError(
                    "tool outcome contains an unsupported failure state"
                )
            provider_payload = {
                "type": "tool_result",
                "call_id": outcome.call_id,
                "tool": {
                    "name": outcome.tool_name,
                    "version": outcome.tool_version,
                },
                "status": outcome.status.value,
                "error": {
                    "code": outcome.error.error_code,
                    "message": outcome.error.public_message,
                },
            }
        else:
            raise UnsupportedProviderContinuationStateError(
                "tool outcome contains an unsupported status"
            )

        try:
            return ProviderContinuationPayload(
                provider_name=self.provider_name,
                call_id=outcome.call_id,
                payload=provider_payload,
            )
        except (ValidationError, PydanticSerializationError) as error:
            raise ProviderContinuationSerializationError(
                "provider continuation payload could not be serialized"
            ) from error
