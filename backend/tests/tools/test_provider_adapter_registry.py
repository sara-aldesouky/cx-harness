"""Unit tests for provider tool-call adapter discovery."""

import inspect

import pytest

from app.tools import (
    DuplicateProviderToolCallAdapterRegistrationError,
    InvalidProviderToolCallAdapterError,
    InvalidProviderToolCallAdapterNameError,
    MockProviderToolCallAdapter,
    ProviderToolCallAdapter,
    ProviderToolCallAdapterNotFoundError,
    ProviderToolCallAdapterRegistry,
    ToolSelections,
)
from app.tools import provider_adapter_registry as registry_module


class FakeAdapter(ProviderToolCallAdapter):
    """Minimal adapter whose call count proves discovery never translates."""

    def __init__(self) -> None:
        self.translation_count = 0

    def translate(self, provider_output: object) -> ToolSelections:
        self.translation_count += 1
        return ()


def test_register_and_lookup_adapter_instance() -> None:
    adapter = MockProviderToolCallAdapter()
    registry = ProviderToolCallAdapterRegistry()

    registry.register("mock", adapter)

    assert registry.get("mock") is adapter
    assert registry.has("mock") is True


def test_provider_names_are_trimmed_and_case_normalized() -> None:
    adapter = FakeAdapter()
    registry = ProviderToolCallAdapterRegistry()

    registry.register("  MoCk  ", adapter)

    assert registry.get(" MOCK ") is adapter
    assert registry.has("mock") is True
    assert registry.list_providers() == ("mock",)


def test_duplicate_normalized_registration_is_rejected() -> None:
    registry = ProviderToolCallAdapterRegistry()
    registry.register("mock", FakeAdapter())

    with pytest.raises(
        DuplicateProviderToolCallAdapterRegistrationError,
        match="already registered",
    ):
        registry.register(" MOCK ", FakeAdapter())


def test_unknown_provider_lookup_is_clear() -> None:
    with pytest.raises(
        ProviderToolCallAdapterNotFoundError,
        match="'unknown' is not registered",
    ):
        ProviderToolCallAdapterRegistry().get("unknown")


def test_has_returns_false_for_unknown_provider() -> None:
    assert ProviderToolCallAdapterRegistry().has("unknown") is False


@pytest.mark.parametrize("invalid", [object(), object, "adapter"])
def test_invalid_adapter_implementation_is_rejected(invalid: object) -> None:
    with pytest.raises(
        InvalidProviderToolCallAdapterError,
        match="must implement ProviderToolCallAdapter",
    ):
        ProviderToolCallAdapterRegistry().register(  # type: ignore[arg-type]
            "mock", invalid
        )


@pytest.mark.parametrize("invalid", ["", "   ", None, 42])
def test_invalid_provider_names_are_rejected(invalid: object) -> None:
    with pytest.raises(InvalidProviderToolCallAdapterNameError):
        ProviderToolCallAdapterRegistry().register(  # type: ignore[arg-type]
            invalid, FakeAdapter()
        )


def test_lookup_and_has_apply_the_same_name_validation() -> None:
    registry = ProviderToolCallAdapterRegistry()

    with pytest.raises(InvalidProviderToolCallAdapterNameError):
        registry.get(" ")
    with pytest.raises(InvalidProviderToolCallAdapterNameError):
        registry.has(1)  # type: ignore[arg-type]


def test_multiple_provider_listing_is_deterministic() -> None:
    registry = ProviderToolCallAdapterRegistry()
    registry.register("ollama", FakeAdapter())
    registry.register("gemini", FakeAdapter())
    registry.register("mock", MockProviderToolCallAdapter())

    first = registry.list_providers()
    second = registry.list_providers()

    assert first == ("gemini", "mock", "ollama")
    assert second == first


def test_discovery_results_are_immutable_snapshots() -> None:
    mock = MockProviderToolCallAdapter()
    ollama = FakeAdapter()
    registry = ProviderToolCallAdapterRegistry()
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
    assert registry.list_providers() == ("mock", "ollama")


def test_registration_and_discovery_never_translate_provider_output() -> None:
    adapter = FakeAdapter()
    registry = ProviderToolCallAdapterRegistry()

    registry.register("fake", adapter)
    registry.get("fake")
    registry.has("fake")
    registry.list_providers()
    registry.items()

    assert adapter.translation_count == 0


def test_registries_are_independent_and_have_no_global_registration() -> None:
    first = ProviderToolCallAdapterRegistry()
    second = ProviderToolCallAdapterRegistry()
    first.register("mock", MockProviderToolCallAdapter())

    assert first.has("mock") is True
    assert second.has("mock") is False


def test_registry_has_no_tool_resolution_database_or_network_dependencies() -> None:
    source = inspect.getsource(registry_module).lower()

    for forbidden in (
        "toolregistry",
        "basetool",
        ".translate(",
        ".execute(",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "requests",
        "modelrun",
    ):
        assert forbidden not in source
