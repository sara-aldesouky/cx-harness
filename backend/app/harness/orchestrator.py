"""Minimal provider-neutral conversation orchestration."""

from __future__ import annotations

from pydantic import ValidationError

from app.providers import ModelRequest, ModelResponse, ProviderRegistry


class ProviderResponseContractError(TypeError):
    """Raised when a provider violates the standardized response contract."""


class ConversationOrchestrator:
    """Coordinate one user message with a registry-resolved model provider.

    The orchestrator owns only request construction, provider resolution,
    invocation, and response-contract validation. It deliberately has no
    knowledge of concrete providers, storage, tools, prompts, or conversation
    state.
    """

    def __init__(self, registry: ProviderRegistry, provider_name: str) -> None:
        if not isinstance(registry, ProviderRegistry):
            raise TypeError("registry must be a ProviderRegistry")
        self._registry = registry
        self._provider_name = provider_name

    def respond(self, user_message: str) -> ModelResponse:
        """Generate one validated standardized response for a user message."""

        request = ModelRequest(prompt=user_message)
        provider = self._registry.get(self._provider_name)
        response = provider.generate(request)

        if not isinstance(response, ModelResponse):
            raise ProviderResponseContractError(
                "provider generate() must return a ModelResponse"
            )

        try:
            validated = ModelResponse.model_validate(response.model_dump())
        except ValidationError as exc:
            raise ProviderResponseContractError(
                "provider returned an invalid ModelResponse"
            ) from exc

        if validated.provider_name != provider.provider_name:
            raise ProviderResponseContractError(
                "response provider_name does not match the resolved provider"
            )
        if validated.model_name != provider.model_name:
            raise ProviderResponseContractError(
                "response model_name does not match the resolved provider"
            )
        return validated
