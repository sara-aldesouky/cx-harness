"""Unit tests for the Stage 7.9 application composition root."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.database.repositories import ModelRunAuditRepository
from app.harness import (
    MockPromptAdapter,
    ModelPipelineCoordinator,
    ModelPipelineStartupError,
    OllamaPromptAdapter,
    PromptAdapterRegistry,
    build_model_pipeline,
)
from app.harness import runtime
from app.providers import (
    DuplicateProviderRegistrationError,
    MockModelProvider,
    ProviderRegistry,
)
from app.providers.ollama_qwen import OllamaQwenProvider


def make_settings(**overrides: object) -> Settings:
    values = {
        "database_url": "postgresql://local:test@localhost/cx_test",
        "ollama_base_url": "http://localhost:11434",
        "ollama_model_name": "qwen3:8b",
        "ollama_connect_timeout_seconds": 1.5,
        "ollama_read_timeout_seconds": 30.0,
    }
    values.update(overrides)
    return Settings(**values)


def test_builds_fully_configured_persistence_enabled_pipeline() -> None:
    session_factory = object()

    pipeline = build_model_pipeline(
        app_settings=make_settings(),
        database_session_factory=session_factory,  # type: ignore[arg-type]
    )

    assert isinstance(pipeline, ModelPipelineCoordinator)
    repository = pipeline._model_run_audit_repository
    assert isinstance(repository, ModelRunAuditRepository)
    assert repository._session_factory is session_factory


def test_registers_configured_provider_and_prompt_adapter() -> None:
    pipeline = build_model_pipeline(
        app_settings=make_settings(ollama_model_name="qwen3:14b"),
        database_session_factory=object(),  # type: ignore[arg-type]
    )

    provider = pipeline._provider_registry.get("ollama")
    adapter = pipeline._adapter_registry.get("ollama")
    assert isinstance(provider, OllamaQwenProvider)
    assert isinstance(adapter, OllamaPromptAdapter)
    assert provider.model_name == "qwen3:14b"
    assert adapter.model_name == "qwen3:14b"


@pytest.mark.parametrize(
    ("field", "environment_name"),
    [
        ("database_url", "DATABASE_URL"),
    ],
)
def test_missing_required_configuration_fails_fast(
    field: str, environment_name: str
) -> None:
    with pytest.raises(ModelPipelineStartupError, match=environment_name):
        build_model_pipeline(
            app_settings=make_settings(**{field: " "}),
            database_session_factory=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("field", ["ollama_base_url", "ollama_model_name"])
def test_missing_provider_configuration_fails_when_settings_load(
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: " "})


def test_invalid_ollama_configuration_fails_at_startup() -> None:
    with pytest.raises(ValidationError, match="local machine"):
        make_settings(ollama_base_url="https://remote.example.com")


def test_database_session_factory_failure_is_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> None:
        raise RuntimeError("database configuration failed")

    monkeypatch.setattr(runtime, "get_session_factory", fail)

    with pytest.raises(ModelPipelineStartupError, match="session factory"):
        build_model_pipeline(app_settings=make_settings())


def test_additional_interface_pair_supports_future_registration() -> None:
    mock_provider = MockModelProvider()
    mock_adapter = MockPromptAdapter()

    pipeline = build_model_pipeline(
        app_settings=make_settings(),
        database_session_factory=object(),  # type: ignore[arg-type]
        additional_registrations=((mock_provider, mock_adapter),),
    )

    assert pipeline._provider_registry.get("mock") is mock_provider
    assert pipeline._adapter_registry.get("mock") is mock_adapter
    assert tuple(
        provider.provider_name for provider in pipeline._provider_registry.list()
    ) == ("mock", "ollama")
    assert tuple(
        adapter.provider_name for adapter in pipeline._adapter_registry.list()
    ) == ("mock", "ollama")


def test_duplicate_provider_registration_surfaces_immediately() -> None:
    with pytest.raises(DuplicateProviderRegistrationError):
        build_model_pipeline(
            app_settings=make_settings(),
            database_session_factory=object(),  # type: ignore[arg-type]
            additional_registrations=(
                (OllamaQwenProvider(), OllamaPromptAdapter()),
            ),
        )


def test_mismatched_provider_adapter_pair_fails_fast() -> None:
    with pytest.raises(ModelPipelineStartupError, match="names must match"):
        build_model_pipeline(
            app_settings=make_settings(),
            database_session_factory=object(),  # type: ignore[arg-type]
            additional_registrations=(
                (MockModelProvider(), OllamaPromptAdapter()),
            ),
        )


def test_factory_uses_registry_abstractions_and_does_not_connect() -> None:
    pipeline = build_model_pipeline(
        app_settings=make_settings(),
        database_session_factory=object(),  # type: ignore[arg-type]
    )

    assert isinstance(pipeline._provider_registry, ProviderRegistry)
    assert isinstance(pipeline._adapter_registry, PromptAdapterRegistry)
