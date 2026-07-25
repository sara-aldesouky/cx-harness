"""Unit tests for provider continuation-adapter discovery."""

import inspect

import pytest

from app.tools import (
    DuplicateProviderContinuationAdapterRegistrationError,
    InvalidProviderContinuationAdapterError,
    InvalidProviderContinuationAdapterNameError,
    MockProviderContinuationAdapter,
    ProviderContinuationAdapter,
    ProviderContinuationAdapterNotFoundError,
    ProviderContinuationAdapterRegistry,
    ProviderContinuationPayload,
    ToolExecutionOutcome,
)
from app.tools import continuation_adapter_registry as registry_module


class FakeContinuationAdapter(ProviderContinuationAdapter):
    """Minimal adapter whose counter proves discovery never translates."""

    def __init__(self, provider_name: str) -> None:
        self._provider_name = provider_name
        self.translation_count = 0

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def translate(
        self, outcome: ToolExecutionOutcome
    ) -> ProviderContinuationPayload:
        self.translation_count += 1
        raise AssertionError("registry must not translate outcomes")


def test_register_and_lookup_mock_adapter_preserves_instance() -> None:
    adapter = MockProviderContinuationAdapter()
    registry = ProviderContinuationAdapterRegistry()

    registry.register("mock", adapter)

    assert registry.get("mock") is adapter
    assert registry.has("mock") is True


def test_provider_identity_is_trimmed_lowercased_and_case_insensitive() -> None:
    adapter = MockProviderContinuationAdapter()
    registry = ProviderContinuationAdapterRegistry()

    registry.register("  MoCk  ", adapter)

    assert registry.get(" MOCK ") is adapter
    assert registry.has("mock") is True
    assert registry.list_providers() == ("mock",)


def test_duplicate_normalized_identity_is_rejected() -> None:
    registry = ProviderContinuationAdapterRegistry()
    registry.register("mock", MockProviderContinuationAdapter())

    with pytest.raises(
        DuplicateProviderContinuationAdapterRegistrationError,
        match="already registered",
    ):
        registry.register(" MOCK ", MockProviderContinuationAdapter())


def test_unknown_provider_lookup_is_clear() -> None:
    with pytest.raises(
        ProviderContinuationAdapterNotFoundError,
        match="'unknown' is not registered",
    ):
        ProviderContinuationAdapterRegistry().get("unknown")


def test_has_returns_false_for_valid_unknown_provider() -> None:
    assert ProviderContinuationAdapterRegistry().has("unknown") is False


@pytest.mark.parametrize("invalid", [object(), object, "adapter"])
def test_invalid_adapter_is_rejected_without_translation(invalid: object) -> None:
    with pytest.raises(
        InvalidProviderContinuationAdapterError,
        match="must implement ProviderContinuationAdapter",
    ):
        ProviderContinuationAdapterRegistry().register(  # type: ignore[arg-type]
            "mock", invalid
        )


@pytest.mark.parametrize("invalid", ["", "   ", None, 42])
def test_invalid_provider_identity_is_rejected(invalid: object) -> None:
    with pytest.raises(InvalidProviderContinuationAdapterNameError):
        ProviderContinuationAdapterRegistry().register(  # type: ignore[arg-type]
            invalid, MockProviderContinuationAdapter()
        )


def test_get_and_has_use_the_same_name_validation() -> None:
    registry = ProviderContinuationAdapterRegistry()

    with pytest.raises(InvalidProviderContinuationAdapterNameError):
        registry.get(" ")
    with pytest.raises(InvalidProviderContinuationAdapterNameError):
        registry.has(1)  # type: ignore[arg-type]


def test_multiple_registrations_have_deterministic_ordering() -> None:
    registry = ProviderContinuationAdapterRegistry()
    registry.register("ollama", FakeContinuationAdapter("ollama"))
    registry.register("gemini", FakeContinuationAdapter("gemini"))
    registry.register("mock", MockProviderContinuationAdapter())

    assert registry.list_providers() == ("gemini", "mock", "ollama")
    assert registry.list_providers() == registry.list_providers()


def test_provider_and_item_discovery_are_immutable_snapshots() -> None:
    mock = MockProviderContinuationAdapter()
    ollama = FakeContinuationAdapter("ollama")
    registry = ProviderContinuationAdapterRegistry()
    registry.register("ollama", ollama)
    registry.register("mock", mock)

    providers = registry.list_providers()
    items = registry.items()

    assert isinstance(providers, tuple)
    assert items == (("mock", mock), ("ollama", ollama))
    with pytest.raises(TypeError):
        providers[0] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        items[0] = ("changed", mock)  # type: ignore[index]
    registry.register("gemini", FakeContinuationAdapter("gemini"))
    assert providers == ("mock", "ollama")
    assert items == (("mock", mock), ("ollama", ollama))


def test_registry_operations_never_translate() -> None:
    adapter = FakeContinuationAdapter("fake")
    registry = ProviderContinuationAdapterRegistry()

    registry.register("fake", adapter)
    registry.get("fake")
    registry.has("fake")
    registry.list_providers()
    registry.items()

    assert adapter.translation_count == 0


def test_registry_instances_are_independent_without_global_state() -> None:
    first = ProviderContinuationAdapterRegistry()
    second = ProviderContinuationAdapterRegistry()
    first.register("mock", MockProviderContinuationAdapter())

    assert first.has("mock") is True
    assert second.has("mock") is False


def test_registry_has_no_cross_registry_runtime_database_or_network_dependencies() -> None:
    source = inspect.getsource(registry_module).lower()

    for forbidden in (
        "provider_tool_call_adapter_registry",
        "toolregistry",
        "basetool",
        "toolexecutionoutcome",
        "providercontinuationpayload",
        ".translate(",
        ".execute(",
        "modelprovider",
        "prompt",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "requests",
        "modelrun",
    ):
        assert forbidden not in source
