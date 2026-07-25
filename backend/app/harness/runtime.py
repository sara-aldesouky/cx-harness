"""Application composition root for the persistence-enabled model pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, settings
from app.database.repositories import ModelRunAuditRepository
from app.database.session import get_session_factory
from app.harness.model_pipeline import ModelPipelineCoordinator
from app.harness.ollama_prompt_adapter import OllamaPromptAdapter
from app.harness.prompt_adapter import PromptAdapter
from app.harness.prompt_adapter_registry import PromptAdapterRegistry
from app.providers.base import ModelProvider
from app.providers.ollama_qwen import OllamaQwenProvider
from app.providers.registry import ProviderRegistry


ProviderAdapterRegistration = tuple[ModelProvider, PromptAdapter]


class ModelPipelineStartupError(RuntimeError):
    """Raised when required runtime dependencies cannot be composed safely."""


def build_model_pipeline(
    *,
    app_settings: Settings = settings,
    database_session_factory: Optional[sessionmaker[Session]] = None,
    additional_registrations: Iterable[ProviderAdapterRegistration] = (),
) -> ModelPipelineCoordinator:
    """Return one fully configured, persistence-enabled model pipeline.

    Production callers need only call this function. Explicit dependency
    arguments exist for tests and future provider registration; they do not
    change ownership between providers, adapters, and persistence.
    """

    _validate_required_settings(app_settings)
    selected_session_factory = database_session_factory
    if selected_session_factory is None:
        try:
            selected_session_factory = get_session_factory()
        except Exception as exc:
            raise ModelPipelineStartupError(
                "failed to configure the database session factory"
            ) from exc

    provider_registry = ProviderRegistry()
    adapter_registry = PromptAdapterRegistry()
    try:
        default_provider = OllamaQwenProvider(
            base_url=app_settings.ollama_base_url,
            model_name=app_settings.ollama_model_name,
            connect_timeout_seconds=(
                app_settings.ollama_connect_timeout_seconds
            ),
            read_timeout_seconds=app_settings.ollama_read_timeout_seconds,
        )
        default_adapter = OllamaPromptAdapter(
            model_name=app_settings.ollama_model_name
        )
    except (TypeError, ValueError) as exc:
        raise ModelPipelineStartupError(
            "invalid Ollama/Qwen runtime configuration"
        ) from exc

    registrations = (
        (default_provider, default_adapter),
        *tuple(additional_registrations),
    )
    for provider, adapter in registrations:
        _validate_registration_pair(provider, adapter)
        provider_registry.register(provider)
        adapter_registry.register(adapter)

    audit_repository = ModelRunAuditRepository(selected_session_factory)
    return ModelPipelineCoordinator(
        provider_registry=provider_registry,
        adapter_registry=adapter_registry,
        model_run_audit_repository=audit_repository,
    )


def _validate_required_settings(app_settings: Settings) -> None:
    if not isinstance(app_settings, Settings):
        raise TypeError("app_settings must be a Settings instance")
    missing = [
        name
        for name, value in (
            ("DATABASE_URL", app_settings.database_url),
            ("OLLAMA_BASE_URL", app_settings.ollama_base_url),
            ("OLLAMA_MODEL_NAME", app_settings.ollama_model_name),
        )
        if not value.strip()
    ]
    if missing:
        raise ModelPipelineStartupError(
            f"missing required model pipeline configuration: {', '.join(missing)}"
        )


def _validate_registration_pair(
    provider: ModelProvider, adapter: PromptAdapter
) -> None:
    if not isinstance(provider, ModelProvider):
        raise TypeError("registered provider must implement ModelProvider")
    if not isinstance(adapter, PromptAdapter):
        raise TypeError("registered adapter must implement PromptAdapter")
    if provider.provider_name != adapter.provider_name:
        raise ModelPipelineStartupError(
            "provider and prompt adapter names must match"
        )
    if provider.model_name != adapter.model_name:
        raise ModelPipelineStartupError(
            "provider and prompt adapter model names must match"
        )
