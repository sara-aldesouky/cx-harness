"""Provider adapter boundary and normalized Stage 14 failures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from app.model_orchestration.contracts import (
    ModelOrchestrationRequest,
    ModelOrchestrationResponse,
    ModelProviderCapabilities,
)


class ProviderFailureCategory(str, Enum):
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    AUTHENTICATION_FAILURE = "authentication_failure"
    RATE_LIMIT = "rate_limit"
    MALFORMED_RESPONSE = "malformed_provider_response"
    EXECUTION_FAILURE = "provider_execution_failure"


class ModelProviderAdapterError(RuntimeError):
    """Safe provider-neutral adapter failure with no SDK exception details."""

    def __init__(
        self,
        category: ProviderFailureCategory,
        public_message: str,
        *,
        retryable: bool = False,
    ) -> None:
        self.category = category
        self.public_message = public_message.strip()
        self.retryable = retryable
        if not self.public_message:
            raise ValueError("public_message must not be blank")
        super().__init__(self.public_message)


class ModelProviderAdapter(ABC):
    """Translate and invoke exactly one concrete provider behind one interface."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_identifier(self) -> str:
        raise NotImplementedError

    @property
    def capabilities(self) -> ModelProviderCapabilities:
        """Declare neutral features; concrete adapters may override this snapshot."""

        return ModelProviderCapabilities()

    @property
    def supports_streaming(self) -> bool:
        """Backward-compatible convenience view over neutral capabilities."""

        return self.capabilities.streaming

    @abstractmethod
    def invoke(
        self, request: ModelOrchestrationRequest
    ) -> ModelOrchestrationResponse:
        """Own provider translation, SDK invocation, and response normalization."""

        raise NotImplementedError
