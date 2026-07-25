"""Provider-neutral end-to-end model pipeline coordination."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from time import monotonic
from typing import Callable, Optional
from uuid import UUID

from pydantic import ValidationError

from app.harness.context_builder import ContextBuilder, MessageInput
from app.harness.prompt import PromptManager
from app.harness.prompt_adapter_registry import PromptAdapterRegistry
from app.database.repositories.model_run_audit_repository import (
    ModelRunAuditWriter,
)
from app.providers.base import ModelResponse
from app.providers.registry import ProviderRegistry


class PipelineIdentityMismatchError(ValueError):
    """Raised when provider, adapter, request, or response identities disagree."""


class PipelineResponseContractError(TypeError):
    """Raised when a provider violates the standardized response contract."""


class ModelRunPersistenceError(RuntimeError):
    """Raised when model invocation state cannot be safely persisted."""

    def __init__(
        self, message: str, *, pipeline_error: Optional[Exception] = None
    ) -> None:
        super().__init__(message)
        self.pipeline_error = pipeline_error


class ModelPipelineCoordinator:
    """Coordinate existing contracts without depending on concrete integrations."""

    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry,
        adapter_registry: PromptAdapterRegistry,
        model_run_audit_repository: Optional[ModelRunAuditWriter] = None,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(provider_registry, ProviderRegistry):
            raise TypeError("provider_registry must be a ProviderRegistry")
        if not isinstance(adapter_registry, PromptAdapterRegistry):
            raise TypeError("adapter_registry must be a PromptAdapterRegistry")
        self._provider_registry = provider_registry
        self._adapter_registry = adapter_registry
        self._model_run_audit_repository = model_run_audit_repository
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock

    def run(
        self,
        *,
        system_instructions: str,
        messages: Iterable[MessageInput],
        provider_name: str,
        model_name: str,
        conversation_id: Optional[UUID] = None,
    ) -> ModelResponse:
        if self._model_run_audit_repository is None:
            return self._execute(
                system_instructions=system_instructions,
                messages=messages,
                provider_name=provider_name,
                model_name=model_name,
            )
        if conversation_id is None:
            raise ModelRunPersistenceError(
                "conversation_id is required when ModelRun persistence is enabled"
            )

        started_at = self._wall_clock()
        started_monotonic = self._monotonic_clock()
        persisted_provider = self._persisted_provider_name(
            provider_name=provider_name, model_name=model_name
        )
        try:
            model_run_id = self._model_run_audit_repository.create_running(
                conversation_id=conversation_id,
                provider=persisted_provider,
                model_name=model_name,
                started_at=started_at,
            )
        except Exception as exc:
            raise ModelRunPersistenceError(
                "failed to create running ModelRun record"
            ) from exc

        try:
            response = self._execute(
                system_instructions=system_instructions,
                messages=messages,
                provider_name=provider_name,
                model_name=model_name,
            )
        except Exception as pipeline_error:
            self._finalize_model_run(
                model_run_id=model_run_id,
                status="failed",
                success=False,
                started_monotonic=started_monotonic,
                error_message=(
                    f"{pipeline_error.__class__.__name__}: {pipeline_error}"
                ),
                pipeline_error=pipeline_error,
            )
            raise

        self._finalize_model_run(
            model_run_id=model_run_id,
            status="completed",
            success=True,
            started_monotonic=started_monotonic,
            error_message=None,
        )
        return response

    def _execute(
        self,
        *,
        system_instructions: str,
        messages: Iterable[MessageInput],
        provider_name: str,
        model_name: str,
    ) -> ModelResponse:
        context = ContextBuilder.build(
            system_instructions=system_instructions,
            messages=messages,
            provider_name=provider_name,
            model_name=model_name,
        )
        prompt = PromptManager.create(context)
        adapter = self._adapter_registry.get(provider_name)
        provider = self._provider_registry.get(provider_name)
        if adapter.provider_name != provider.provider_name:
            raise PipelineIdentityMismatchError(
                "prompt adapter and model provider identities do not match"
            )
        if adapter.model_name != provider.model_name:
            raise PipelineIdentityMismatchError(
                "prompt adapter and model provider model names do not match"
            )
        request = adapter.adapt(prompt)
        response = provider.generate_provider_request(request)
        if not isinstance(response, ModelResponse):
            raise PipelineResponseContractError(
                "model provider must return a ModelResponse"
            )
        try:
            validated = ModelResponse.model_validate(response.model_dump())
        except ValidationError as exc:
            raise PipelineResponseContractError(
                "model provider returned an invalid ModelResponse"
            ) from exc
        if validated.provider_name != provider.provider_name:
            raise PipelineIdentityMismatchError(
                "response provider identity does not match provider"
            )
        if validated.model_name != provider.model_name:
            raise PipelineIdentityMismatchError(
                "response model identity does not match provider"
            )
        return validated

    def _finalize_model_run(
        self,
        *,
        model_run_id: UUID,
        status: str,
        success: bool,
        started_monotonic: float,
        error_message: Optional[str],
        pipeline_error: Optional[Exception] = None,
    ) -> None:
        finished_at = self._wall_clock()
        latency_ms = max(
            0,
            int((self._monotonic_clock() - started_monotonic) * 1000),
        )
        try:
            assert self._model_run_audit_repository is not None
            self._model_run_audit_repository.finalize(
                model_run_id,
                status=status,
                success=success,
                finished_at=finished_at,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        except Exception as exc:
            raise ModelRunPersistenceError(
                "failed to finalize ModelRun record",
                pipeline_error=pipeline_error,
            ) from exc

    @staticmethod
    def _persisted_provider_name(*, provider_name: str, model_name: str) -> str:
        normalized_provider = provider_name.strip().lower()
        normalized_model = model_name.strip().lower()
        if normalized_provider == "ollama" and normalized_model.startswith("qwen"):
            return "qwen"
        if normalized_provider in {"gemini", "qwen", "fanar"}:
            return normalized_provider
        raise ModelRunPersistenceError(
            "provider cannot be represented by the existing ModelRun schema"
        )
