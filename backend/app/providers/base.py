"""Provider-neutral contracts for text-generation model adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.tools.selection import ToolSelectionRequest

if TYPE_CHECKING:
    from app.harness.prompt_adapter import ProviderRequest
    from app.services.model_continuation_service import ModelContinuationRequest
    from app.services.model_tool_loop_service import ModelToolLoopTurnRequest



class ProviderCapabilities(BaseModel):
    """Immutable features declared by a model provider implementation.

    These flags describe compatibility only. Stage 7.1 does not implement any
    of the capabilities or change how requests are generated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_calling: bool = False
    streaming: bool = False
    structured_output: bool = False


class ModelRequest(BaseModel):
    """Minimal provider-independent input accepted by every model adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        """Normalize surrounding whitespace and reject an empty request."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("prompt must not be empty or whitespace")
        return normalized


class ModelResponse(BaseModel):
    """Minimal provider-independent output returned by every model adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str
    provider_name: str
    model_name: str

    @field_validator("content", "provider_name", "model_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """Normalize required response text and reject blank values."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty or whitespace")
        return normalized


class ModelToolLoopTurnResponse(BaseModel):
    """Normalized result of one model turn in a bounded tool loop.

    A turn returns either a terminal assistant response or an ordered collection
    of provider-neutral tool selections. Provider-specific payload parsing stays
    inside provider implementations and adapters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    final_response: Optional[ModelResponse] = None
    tool_calls: tuple["ToolSelectionRequest", ...] = ()
    assistant_content: Optional[str] = None

    @field_validator("assistant_content")
    @classmethod
    def normalize_optional_content(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("assistant_content must not be blank")
        return normalized

    @field_validator("tool_calls")
    @classmethod
    def require_unique_call_ids(
        cls, value: tuple["ToolSelectionRequest", ...]
    ) -> tuple["ToolSelectionRequest", ...]:
        call_ids = tuple(call.call_id for call in value)
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool call IDs must be unique within one model turn")
        return value

    @field_validator("final_response")
    @classmethod
    def validate_terminal_response(
        cls, value: Optional[ModelResponse]
    ) -> Optional[ModelResponse]:
        return value

    def model_post_init(self, __context: object) -> None:
        if (self.final_response is None) == (not self.tool_calls):
            raise ValueError(
                "a model turn must contain either one final response or tool calls"
            )


class ModelProvider(ABC):
    """Stable boundary between the harness and a concrete model provider.

    Provider implementations own model-specific transport and translation.
    Callers depend only on this contract, so selecting Qwen, Fanar, Gemini, or
    another future adapter does not change harness code.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the normalized name used to register this provider."""

        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the provider-specific model identifier."""

        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return immutable capabilities advertised by the provider."""

        raise NotImplementedError

    @abstractmethod
    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate one standardized response from a validated request."""

        raise NotImplementedError

    def generate_provider_request(
        self, request: ProviderRequest
    ) -> ModelResponse:
        """Generate from a structured adapter request when supported.

        This bridge is backward-compatible: the original text request path
        remains available and providers opt into structured requests.
        """

        raise StructuredProviderRequestNotSupportedError(
            f"provider {self.provider_name!r} does not support structured requests"
        )

    def continue_model(
        self, request: ModelContinuationRequest
    ) -> ModelResponse:
        """Continue once from a provider-owned tool-result payload when supported."""

        raise ModelContinuationNotSupportedError(
            f"provider {self.provider_name!r} does not support model continuation"
        )

    def run_tool_loop_turn(
        self, request: "ModelToolLoopTurnRequest"
    ) -> ModelToolLoopTurnResponse:
        """Run one bounded-loop turn when a provider supports normalized tools."""

        raise ModelToolLoopNotSupportedError(
            f"provider {self.provider_name!r} does not support the model tool loop"
        )


class StructuredProviderRequestNotSupportedError(NotImplementedError):
    """Raised when a provider has no structured-request implementation."""


class ModelContinuationNotSupportedError(NotImplementedError):
    """Raised when a provider has no continuation-request implementation."""


class ModelToolLoopNotSupportedError(NotImplementedError):
    """Raised when a provider has no normalized bounded-loop implementation."""
