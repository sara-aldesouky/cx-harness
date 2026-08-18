"""Single provider-neutral orchestration service for normalized model calls."""

from __future__ import annotations

from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError as FutureCancelledError
from time import monotonic
from typing import Callable

from pydantic import BaseModel, ConfigDict, field_validator

from app.model_orchestration.adapter import (
    ModelProviderAdapterError,
    ProviderFailureCategory,
)
from app.model_orchestration.contracts import (
    ModelOrchestrationRequest,
    ModelOrchestrationResponse,
)
from app.model_orchestration.registry import (
    ModelAdapterNotFoundError,
    ModelProviderAdapterRegistry,
)


class ModelOrchestratorConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_name: str
    model_identifier: str

    @field_validator("provider_name")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("provider_name must not be blank")
        return normalized

    @field_validator("model_identifier")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model_identifier must not be blank")
        return normalized


class ModelOrchestrationError(RuntimeError):
    """Only failure exposed by the orchestrator application boundary."""

    def __init__(
        self,
        category: ProviderFailureCategory,
        public_message: str,
        *,
        retryable: bool = False,
    ) -> None:
        self.category = category
        self.public_message = public_message
        self.retryable = retryable
        super().__init__(public_message)


class ModelOrchestrator:
    """Resolve one configured adapter and return one validated neutral response."""

    def __init__(
        self,
        registry: ModelProviderAdapterRegistry,
        configuration: ModelOrchestratorConfiguration,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(registry, ModelProviderAdapterRegistry):
            raise TypeError("registry must be a ModelProviderAdapterRegistry")
        if not isinstance(configuration, ModelOrchestratorConfiguration):
            raise TypeError("configuration must be a ModelOrchestratorConfiguration")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._registry = registry
        self._configuration = configuration
        self._clock = clock

    def orchestrate(
        self, request: ModelOrchestrationRequest
    ) -> ModelOrchestrationResponse:
        if not isinstance(request, ModelOrchestrationRequest):
            raise TypeError("request must be a ModelOrchestrationRequest")
        try:
            adapter = self._registry.get(self._configuration.provider_name)
        except ModelAdapterNotFoundError:
            raise ModelOrchestrationError(
                ProviderFailureCategory.UNAVAILABLE,
                "The configured model provider is unavailable.",
                retryable=True,
            ) from None
        if (
            adapter.provider_name.strip().lower()
            != self._configuration.provider_name
            or adapter.model_identifier != self._configuration.model_identifier
        ):
            raise ModelOrchestrationError(
                ProviderFailureCategory.MALFORMED_RESPONSE,
                "The configured model provider identity is invalid.",
            )

        started = self._clock()
        try:
            response = adapter.invoke(request)
        except (AsyncCancelledError, FutureCancelledError):
            raise
        except ModelProviderAdapterError as error:
            raise ModelOrchestrationError(
                error.category,
                error.public_message,
                retryable=error.retryable,
            ) from None
        except Exception:
            raise ModelOrchestrationError(
                ProviderFailureCategory.EXECUTION_FAILURE,
                "The model provider failed to complete the request.",
            ) from None
        latency_ms = max(0, int((self._clock() - started) * 1000))

        if not isinstance(response, ModelOrchestrationResponse):
            raise ModelOrchestrationError(
                ProviderFailureCategory.MALFORMED_RESPONSE,
                "The model provider returned an invalid response.",
            )
        try:
            validated = ModelOrchestrationResponse.model_validate(
                response.model_dump(mode="python")
            )
        except (TypeError, ValueError):
            raise ModelOrchestrationError(
                ProviderFailureCategory.MALFORMED_RESPONSE,
                "The model provider returned an invalid response.",
            ) from None
        if (
            validated.metadata.provider_name.strip().lower()
            != self._configuration.provider_name
            or validated.metadata.model_identifier
            != self._configuration.model_identifier
        ):
            raise ModelOrchestrationError(
                ProviderFailureCategory.MALFORMED_RESPONSE,
                "The model provider returned inconsistent identity metadata.",
            )
        normalized_payload = validated.model_dump(mode="json")
        normalized_payload["metadata"]["latency_ms"] = latency_ms
        return ModelOrchestrationResponse.model_validate(normalized_payload)
