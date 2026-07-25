"""Pure unit tests for the Stage 7.2 conversation orchestrator."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.harness import ConversationOrchestrator, ProviderResponseContractError
from app.providers import (
    MockModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderCapabilities,
    ProviderNotFoundError,
    ProviderRegistry,
)


class RecordingMockProvider(MockModelProvider):
    """Mock provider that exposes the standardized request received by a test."""

    def __init__(self) -> None:
        self.received_request: ModelRequest | None = None

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.received_request = request
        return super().generate(request)


class InvalidTypeProvider(MockModelProvider):
    def generate(self, request: ModelRequest) -> ModelResponse:
        return {"content": "invalid"}  # type: ignore[return-value]


class InvalidResponseProvider(MockModelProvider):
    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse.model_construct(
            content="",
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


class WrongIdentityProvider(MockModelProvider):
    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="response",
            provider_name="another-provider",
            model_name=self.model_name,
        )


def build_orchestrator(
    provider: MockModelProvider | None = None,
) -> tuple[ConversationOrchestrator, MockModelProvider]:
    selected = provider or MockModelProvider()
    registry = ProviderRegistry()
    registry.register(selected)
    return ConversationOrchestrator(registry, selected.provider_name), selected


def test_successful_orchestration_with_mock_provider() -> None:
    orchestrator, provider = build_orchestrator()

    response = orchestrator.respond("Where is my order?")

    assert response == ModelResponse(
        content="Mock response: Where is my order?",
        provider_name=provider.provider_name,
        model_name=provider.model_name,
    )


def test_orchestrator_constructs_standardized_request() -> None:
    provider = RecordingMockProvider()
    orchestrator, _ = build_orchestrator(provider)

    orchestrator.respond("  normalized user message  ")

    assert provider.received_request == ModelRequest(
        prompt="normalized user message"
    )


def test_orchestrator_resolves_provider_through_registry() -> None:
    provider = RecordingMockProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    orchestrator = ConversationOrchestrator(registry, " MOCK ")

    orchestrator.respond("hello")

    assert provider.received_request is not None


def test_unknown_provider_error_is_preserved() -> None:
    orchestrator = ConversationOrchestrator(ProviderRegistry(), "missing")

    with pytest.raises(ProviderNotFoundError, match="missing"):
        orchestrator.respond("hello")


@pytest.mark.parametrize("message", ["", "   "])
def test_invalid_user_message_is_rejected(message: str) -> None:
    orchestrator, _ = build_orchestrator()

    with pytest.raises(ValidationError):
        orchestrator.respond(message)


def test_nonstandard_provider_response_is_rejected() -> None:
    orchestrator, _ = build_orchestrator(InvalidTypeProvider())

    with pytest.raises(ProviderResponseContractError, match="ModelResponse"):
        orchestrator.respond("hello")


def test_invalid_constructed_response_is_revalidated_and_rejected() -> None:
    orchestrator, _ = build_orchestrator(InvalidResponseProvider())

    with pytest.raises(ProviderResponseContractError, match="invalid"):
        orchestrator.respond("hello")


def test_response_identity_must_match_resolved_provider() -> None:
    orchestrator, _ = build_orchestrator(WrongIdentityProvider())

    with pytest.raises(ProviderResponseContractError, match="provider_name"):
        orchestrator.respond("hello")


def test_orchestration_is_deterministic() -> None:
    orchestrator, _ = build_orchestrator()

    first = orchestrator.respond("same input")
    second = orchestrator.respond("same input")

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_orchestrator_has_no_database_or_network_configuration() -> None:
    orchestrator, _ = build_orchestrator()

    assert vars(orchestrator).keys() == {"_registry", "_provider_name"}
    assert ProviderCapabilities() == MockModelProvider().capabilities
