"""Pure unit tests for the Stage 7.1 provider architecture."""

import json

import pytest
from pydantic import ValidationError

from app.providers import (
    DuplicateProviderRegistrationError,
    MockModelProvider,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderCapabilities,
    ProviderNotFoundError,
    ProviderRegistry,
)


def test_model_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        ModelProvider()


def test_request_is_normalized_immutable_and_serializable() -> None:
    request = ModelRequest(prompt="  Hello model  ")

    assert request.prompt == "Hello model"
    assert json.loads(request.model_dump_json()) == {"prompt": "Hello model"}
    with pytest.raises(ValidationError):
        request.prompt = "changed"


@pytest.mark.parametrize("prompt", ["", "   "])
def test_request_rejects_blank_prompt(prompt: str) -> None:
    with pytest.raises(ValidationError):
        ModelRequest(prompt=prompt)


def test_response_and_capabilities_are_standardized() -> None:
    response = ModelResponse(
        content=" answer ", provider_name=" mock ", model_name=" model-v1 "
    )
    capabilities = ProviderCapabilities(
        tool_calling=True,
        streaming=False,
        structured_output=True,
    )

    assert response.model_dump(mode="json") == {
        "content": "answer",
        "provider_name": "mock",
        "model_name": "model-v1",
    }
    assert capabilities.model_dump(mode="json") == {
        "tool_calling": True,
        "streaming": False,
        "structured_output": True,
    }


def test_mock_provider_is_complete_deterministic_and_offline() -> None:
    provider = MockModelProvider()
    request = ModelRequest(prompt="Where is my order?")

    first = provider.generate(request)
    second = provider.generate(request)

    assert isinstance(provider, ModelProvider)
    assert provider.provider_name == "mock"
    assert provider.model_name == "mock-deterministic-v1"
    assert provider.capabilities == ProviderCapabilities()
    assert first == second
    assert first.content == "Mock response: Where is my order?"
    assert first.provider_name == provider.provider_name
    assert first.model_name == provider.model_name


def test_mock_provider_rejects_nonstandard_request() -> None:
    with pytest.raises(TypeError, match="ModelRequest"):
        MockModelProvider().generate("prompt")  # type: ignore[arg-type]


def test_registry_registers_and_looks_up_provider() -> None:
    registry = ProviderRegistry()
    provider = MockModelProvider()

    registry.register(provider)

    assert registry.has("mock") is True
    assert registry.has(" MOCK ") is True
    assert registry.get("Mock") is provider


def test_registry_rejects_duplicate_provider_name() -> None:
    registry = ProviderRegistry()
    registry.register(MockModelProvider())

    with pytest.raises(DuplicateProviderRegistrationError):
        registry.register(MockModelProvider())


def test_registry_reports_unknown_provider() -> None:
    registry = ProviderRegistry()

    assert registry.has("missing") is False
    with pytest.raises(ProviderNotFoundError, match="missing"):
        registry.get("missing")


def test_registry_rejects_invalid_provider() -> None:
    with pytest.raises(TypeError, match="ModelProvider"):
        ProviderRegistry().register(object())  # type: ignore[arg-type]


def test_registry_listing_is_deterministic() -> None:
    class ZetaProvider(MockModelProvider):
        @property
        def provider_name(self) -> str:
            return "zeta"

    registry = ProviderRegistry()
    zeta = ZetaProvider()
    mock = MockModelProvider()
    registry.register(zeta)
    registry.register(mock)

    assert registry.list() == (mock, zeta)
    assert registry.list() == registry.list()
