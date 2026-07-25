"""Provider-neutral boundary for exactly one terminal model continuation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from app.harness.context import ConversationContext
from app.providers.base import ModelResponse
from app.providers.registry import ProviderRegistry, ProviderNotFoundError
from app.tools.continuation_adapter import ProviderContinuationPayload
from app.tools.continuation_cycle import ToolContinuationCycle


class ModelContinuationRequest(BaseModel):
    """Immutable neutral input for one provider-owned continuation translation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_name: str
    model_name: str
    context: ConversationContext
    continuation_payload: ProviderContinuationPayload

    @field_validator("provider_name")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("provider_name must not be empty")
        return normalized

    @field_validator("model_name")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model_name must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_identity(self) -> ModelContinuationRequest:
        if self.continuation_payload.provider_name != self.provider_name:
            raise ValueError("continuation payload provider identity does not match")
        if self.context.provider_name is None or self.context.model_name is None:
            raise ValueError("continuation context requires provider and model identity")
        if self.context.provider_name.strip().lower() != self.provider_name:
            raise ValueError("continuation context provider identity does not match")
        if self.context.model_name != self.model_name:
            raise ValueError("continuation context model identity does not match")
        return self


class SingleModelContinuationServiceError(Exception):
    """Base error for one model-continuation invocation."""


class InvalidModelContinuationInputError(
    SingleModelContinuationServiceError, TypeError
):
    """Raised when continuation does not begin from trusted completed contracts."""


class ModelContinuationProviderMismatchError(SingleModelContinuationServiceError):
    """Raised when provider identity changes across continuation boundaries."""


class ModelContinuationModelMismatchError(SingleModelContinuationServiceError):
    """Raised when continuation attempts to switch model identity."""


class ModelContinuationRequestCreationError(SingleModelContinuationServiceError):
    """Raised when the neutral continuation request cannot be constructed."""


class ModelContinuationInvocationError(SingleModelContinuationServiceError):
    """Raised when provider lookup or one continuation invocation fails."""


class InvalidModelContinuationResponseError(SingleModelContinuationServiceError):
    """Raised when a provider violates the canonical response contract."""


class AdditionalToolCallNotSupportedError(SingleModelContinuationServiceError):
    """Raised when the terminal Stage 8 response requests another tool call."""


class SingleModelContinuationService:
    """Resolve one provider and invoke one terminal continuation exactly once."""

    def __init__(self, provider_registry: ProviderRegistry) -> None:
        if not isinstance(provider_registry, ProviderRegistry):
            raise TypeError("provider_registry must be a ProviderRegistry")
        self._provider_registry = provider_registry

    def continue_once(
        self,
        *,
        provider_name: str,
        model_name: str,
        cycle: ToolContinuationCycle,
        context: ConversationContext,
    ) -> ModelResponse:
        """Submit one completed cycle and return one terminal response unchanged."""

        if not isinstance(provider_name, str) or not provider_name.strip():
            raise InvalidModelContinuationInputError(
                "provider_name must be a non-empty string"
            )
        if not isinstance(model_name, str) or not model_name.strip():
            raise InvalidModelContinuationInputError(
                "model_name must be a non-empty string"
            )
        if not isinstance(cycle, ToolContinuationCycle):
            raise InvalidModelContinuationInputError(
                "cycle must be a completed ToolContinuationCycle"
            )
        if not isinstance(context, ConversationContext):
            raise InvalidModelContinuationInputError(
                "context must be a ConversationContext"
            )

        normalized_provider = provider_name.strip().lower()
        normalized_model = model_name.strip()
        call_id = cycle.continuation_payload.call_id
        if (
            cycle.provider_name != normalized_provider
            or cycle.continuation_payload.provider_name != normalized_provider
        ):
            raise ModelContinuationProviderMismatchError(
                "completed cycle provider does not match continuation provider "
                f"{normalized_provider!r} for call ID {call_id!r}"
            )
        if context.provider_name is None or context.model_name is None:
            raise InvalidModelContinuationInputError(
                "continuation context requires provider and model identity"
            )
        if context.provider_name.strip().lower() != normalized_provider:
            raise ModelContinuationProviderMismatchError(
                "continuation context provider does not match provider "
                f"{normalized_provider!r} for call ID {call_id!r}"
            )
        if context.model_name != normalized_model:
            raise ModelContinuationModelMismatchError(
                "continuation context model does not match model "
                f"{normalized_model!r} for call ID {call_id!r}"
            )

        try:
            provider = self._provider_registry.get(provider_name)
        except (ProviderNotFoundError, TypeError, ValueError) as error:
            raise ModelContinuationInvocationError(
                f"model provider lookup failed for provider {normalized_provider!r}"
            ) from error
        if provider.provider_name.strip().lower() != normalized_provider:
            raise ModelContinuationProviderMismatchError(
                "resolved model provider identity does not match provider "
                f"{normalized_provider!r}"
            )
        if provider.model_name != normalized_model:
            raise ModelContinuationModelMismatchError(
                "resolved provider model does not match model "
                f"{normalized_model!r}"
            )

        try:
            request = ModelContinuationRequest(
                provider_name=normalized_provider,
                model_name=normalized_model,
                context=context,
                continuation_payload=cycle.continuation_payload,
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise ModelContinuationRequestCreationError(
                "model continuation request creation failed for "
                f"provider {normalized_provider!r}, model {normalized_model!r}, "
                f"call ID {call_id!r}"
            ) from error

        try:
            response = provider.continue_model(request)
        except Exception as error:
            raise ModelContinuationInvocationError(
                "model continuation invocation failed for "
                f"provider {normalized_provider!r}, model {normalized_model!r}, "
                f"call ID {call_id!r}"
            ) from error

        if not isinstance(response, ModelResponse):
            raise InvalidModelContinuationResponseError(
                "model continuation returned an invalid response for "
                f"provider {normalized_provider!r}, model {normalized_model!r}"
            )
        try:
            ModelResponse.model_validate(
                {
                    "content": response.content,
                    "provider_name": response.provider_name,
                    "model_name": response.model_name,
                }
            )
        except (ValidationError, AttributeError) as error:
            raise InvalidModelContinuationResponseError(
                "model continuation returned a malformed canonical response"
            ) from error
        if response.provider_name.strip().lower() != normalized_provider:
            raise ModelContinuationProviderMismatchError(
                "continuation response provider identity does not match"
            )
        if response.model_name != normalized_model:
            raise ModelContinuationModelMismatchError(
                "continuation response model identity does not match"
            )

        tool_calls = getattr(response, "tool_calls", ())
        finish_reason = getattr(response, "finish_reason", None)
        if tool_calls or finish_reason in {"tool_call", "tool_calls", "function_call"}:
            raise AdditionalToolCallNotSupportedError(
                "additional tool calls are not supported by the Stage 8 continuation"
            )
        return response
