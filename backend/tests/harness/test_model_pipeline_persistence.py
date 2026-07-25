"""Unit tests for Stage 7.8 ModelRun invocation persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import pytest

from app.harness import (
    ModelPipelineCoordinator,
    ModelRunPersistenceError,
    PromptAdapter,
    PromptAdapterRegistry,
    PromptPackage,
    ProviderRequest,
    ProviderRequestMessage,
)
from app.providers import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderCapabilities,
    ProviderRegistry,
)


class RecordingAuditWriter:
    def __init__(self) -> None:
        self.model_run_id = uuid4()
        self.created: list[dict[str, object]] = []
        self.finalized: list[dict[str, object]] = []
        self.create_error: Optional[Exception] = None
        self.finalize_error: Optional[Exception] = None

    def create_running(
        self,
        *,
        conversation_id: UUID,
        provider: str,
        model_name: str,
        started_at: datetime,
    ) -> UUID:
        if self.create_error is not None:
            raise self.create_error
        self.created.append(
            {
                "conversation_id": conversation_id,
                "provider": provider,
                "model_name": model_name,
                "started_at": started_at,
            }
        )
        return self.model_run_id

    def finalize(
        self,
        model_run_id: UUID,
        *,
        status: str,
        success: bool,
        finished_at: datetime,
        latency_ms: int,
        error_message: Optional[str],
    ) -> None:
        if self.finalize_error is not None:
            raise self.finalize_error
        self.finalized.append(
            {
                "model_run_id": model_run_id,
                "status": status,
                "success": success,
                "finished_at": finished_at,
                "latency_ms": latency_ms,
                "error_message": error_message,
            }
        )


class FakePromptAdapter(PromptAdapter):
    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return "fake-model"

    def _translate(self, prompt: PromptPackage) -> ProviderRequest:
        return ProviderRequest(
            provider_name=self.provider_name,
            model_name=self.model_name,
            system_instructions=prompt.system_instructions,
            messages=tuple(
                ProviderRequestMessage.model_validate(message.model_dump())
                for message in prompt.messages
            ),
        )


class FakeModelProvider(ModelProvider):
    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.invocations = 0

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return "fake-model"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def generate(self, request: ModelRequest) -> ModelResponse:
        raise AssertionError("structured pipeline must not use text generation")

    def generate_provider_request(
        self, request: ProviderRequest
    ) -> ModelResponse:
        self.invocations += 1
        if self.error is not None:
            raise self.error
        return ModelResponse(
            content="provider-independent response",
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


def make_persistent_coordinator(
    writer: RecordingAuditWriter,
    *,
    provider: Optional[FakeModelProvider] = None,
    wall_times: Optional[list[datetime]] = None,
    monotonic_times: Optional[list[float]] = None,
) -> tuple[ModelPipelineCoordinator, FakeModelProvider]:
    selected_provider = provider or FakeModelProvider()
    providers = ProviderRegistry()
    providers.register(selected_provider)
    adapters = PromptAdapterRegistry()
    adapters.register(FakePromptAdapter())
    walls = iter(
        wall_times
        or [
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        ]
    )
    monotonic_values = iter(monotonic_times or [10.0, 10.25])
    return (
        ModelPipelineCoordinator(
            provider_registry=providers,
            adapter_registry=adapters,
            model_run_audit_repository=writer,
            wall_clock=lambda: next(walls),
            monotonic_clock=lambda: next(monotonic_values),
        ),
        selected_provider,
    )


def run_pipeline(
    coordinator: ModelPipelineCoordinator,
    *,
    conversation_id: Optional[UUID] = None,
) -> ModelResponse:
    return coordinator.run(
        system_instructions="instructions",
        messages=[{"role": "user", "content": "hello"}],
        provider_name="gemini",
        model_name="fake-model",
        conversation_id=conversation_id or uuid4(),
    )


def test_successful_execution_persists_complete_lifecycle() -> None:
    writer = RecordingAuditWriter()
    conversation_id = uuid4()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    finish = start + timedelta(seconds=1)
    coordinator, provider = make_persistent_coordinator(
        writer,
        wall_times=[start, finish],
        monotonic_times=[50.0, 50.375],
    )

    response = run_pipeline(coordinator, conversation_id=conversation_id)

    assert response.content == "provider-independent response"
    assert provider.invocations == 1
    assert writer.created == [
        {
            "conversation_id": conversation_id,
            "provider": "gemini",
            "model_name": "fake-model",
            "started_at": start,
        }
    ]
    assert writer.finalized == [
        {
            "model_run_id": writer.model_run_id,
            "status": "completed",
            "success": True,
            "finished_at": finish,
            "latency_ms": 375,
            "error_message": None,
        }
    ]


def test_failed_execution_is_persisted_and_original_error_is_reraised() -> None:
    writer = RecordingAuditWriter()
    original = RuntimeError("model unavailable")
    coordinator, provider = make_persistent_coordinator(
        writer, provider=FakeModelProvider(error=original)
    )

    with pytest.raises(RuntimeError) as captured:
        run_pipeline(coordinator)

    assert captured.value is original
    assert provider.invocations == 1
    assert writer.finalized[0]["status"] == "failed"
    assert writer.finalized[0]["success"] is False
    assert writer.finalized[0]["latency_ms"] == 250
    assert writer.finalized[0]["error_message"] == (
        "RuntimeError: model unavailable"
    )


def test_latency_is_non_negative_when_monotonic_clock_moves_backward() -> None:
    writer = RecordingAuditWriter()
    coordinator, _ = make_persistent_coordinator(
        writer, monotonic_times=[10.0, 9.0]
    )

    run_pipeline(coordinator)

    assert writer.finalized[0]["latency_ms"] == 0


def test_missing_conversation_is_rejected_before_invocation() -> None:
    writer = RecordingAuditWriter()
    coordinator, provider = make_persistent_coordinator(writer)

    with pytest.raises(ModelRunPersistenceError, match="conversation_id"):
        coordinator.run(
            system_instructions="instructions",
            messages=[{"role": "user", "content": "hello"}],
            provider_name="gemini",
            model_name="fake-model",
        )

    assert writer.created == []
    assert provider.invocations == 0


def test_create_failure_is_clear_and_prevents_provider_invocation() -> None:
    writer = RecordingAuditWriter()
    writer.create_error = RuntimeError("database unavailable")
    coordinator, provider = make_persistent_coordinator(writer)

    with pytest.raises(ModelRunPersistenceError, match="create running"):
        run_pipeline(coordinator)

    assert provider.invocations == 0
    assert writer.finalized == []


def test_success_finalize_failure_is_surfaced() -> None:
    writer = RecordingAuditWriter()
    writer.finalize_error = RuntimeError("commit failed")
    coordinator, provider = make_persistent_coordinator(writer)

    with pytest.raises(ModelRunPersistenceError, match="finalize") as captured:
        run_pipeline(coordinator)

    assert captured.value.pipeline_error is None
    assert provider.invocations == 1


def test_failure_finalize_failure_preserves_pipeline_error_context() -> None:
    writer = RecordingAuditWriter()
    writer.finalize_error = RuntimeError("commit failed")
    original = ValueError("invalid response")
    coordinator, _ = make_persistent_coordinator(
        writer, provider=FakeModelProvider(error=original)
    )

    with pytest.raises(ModelRunPersistenceError) as captured:
        run_pipeline(coordinator)

    assert captured.value.pipeline_error is original


def test_unsupported_provider_cannot_be_misrepresented_in_existing_schema() -> None:
    with pytest.raises(ModelRunPersistenceError, match="existing ModelRun schema"):
        ModelPipelineCoordinator._persisted_provider_name(
            provider_name="unknown", model_name="model"
        )


def test_local_ollama_qwen_maps_to_existing_qwen_provider_value() -> None:
    assert ModelPipelineCoordinator._persisted_provider_name(
        provider_name="ollama", model_name="qwen3:8b"
    ) == "qwen"
