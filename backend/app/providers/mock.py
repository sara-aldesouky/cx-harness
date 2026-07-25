"""Deterministic offline provider for development and automated tests."""

from __future__ import annotations

from app.providers.base import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderCapabilities,
)


class MockModelProvider(ModelProvider):
    """Complete provider implementation with no network or external dependency."""

    _capabilities = ProviderCapabilities()

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-deterministic-v1"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not isinstance(request, ModelRequest):
            raise TypeError("request must be a ModelRequest")
        return ModelResponse(
            content=f"Mock response: {request.prompt}",
            provider_name=self.provider_name,
            model_name=self.model_name,
        )
