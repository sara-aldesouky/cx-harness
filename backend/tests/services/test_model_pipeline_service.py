"""Unit tests for the Stage 7.10 model-pipeline application service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.authentication import TrustedCustomerIdentity
from app.harness import ConversationMessage
from app.harness.production_prompt import PRODUCTION_SYSTEM_PROMPT
from app.providers import ModelResponse
from app.services import (
    ModelPipelineService,
    ModelPipelineServiceConfigurationError,
    ModelPipelineServiceInputError,
    ModelPipelineServiceResult,
)
from app.services import model_pipeline_service


class FakePipeline:
    def __init__(
        self,
        *,
        response: Optional[ModelResponse] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.response = response or ModelResponse(
            content="application response",
            provider_name="ollama",
            model_name="qwen3:8b",
        )
        self.error = error
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs: object) -> ModelResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def invoke(
    service: ModelPipelineService,
    *,
    conversation_id: Optional[UUID] = None,
    current_user_message: str = "Current question",
    conversation_history=(),
    system_instructions: str = "Be helpful.",
) -> ModelPipelineServiceResult:
    now = datetime.now(timezone.utc)
    return service.invoke(
        conversation_id=conversation_id or uuid4(),
        current_user_message=current_user_message,
        conversation_history=conversation_history,
        system_instructions=system_instructions,
        trusted_identity=TrustedCustomerIdentity(
            customer_id=uuid4(),
            authenticated_at=now,
            expires_at=now + timedelta(hours=1),
            authentication_method="test",
        ),
    )


def test_successful_invocation_and_clean_result_mapping() -> None:
    pipeline = FakePipeline()
    service = ModelPipelineService(pipeline=pipeline)

    result = invoke(service)

    assert result == ModelPipelineServiceResult(
        content="application response",
        provider_name="ollama",
        model_name="qwen3:8b",
    )
    assert len(pipeline.calls) == 1
    assert not hasattr(result, "database_session")
    assert not hasattr(result, "provider_payload")


def test_conversation_identity_and_context_inputs_are_propagated() -> None:
    pipeline = FakePipeline()
    conversation_id = uuid4()
    history = [
        {"role": "user", "content": " first "},
        {"role": "assistant", "content": " second "},
    ]
    service = ModelPipelineService(
        pipeline=pipeline,
        provider_name="ollama",
        model_name="qwen3:8b",
    )

    invoke(
        service,
        conversation_id=conversation_id,
        current_user_message=" latest ",
        conversation_history=history,
        system_instructions=" instructions ",
    )

    call = pipeline.calls[0]
    assert call["conversation_id"] == conversation_id
    assert call["system_instructions"].startswith(PRODUCTION_SYSTEM_PROMPT)
    assert call["system_instructions"].endswith("instructions")
    assert call["system_instructions"].count(PRODUCTION_SYSTEM_PROMPT) == 1
    assert call["provider_name"] == "ollama"
    assert call["model_name"] == "qwen3:8b"
    messages = call["messages"]
    assert isinstance(messages, tuple)
    assert all(isinstance(message, ConversationMessage) for message in messages)
    assert tuple(message.content for message in messages) == (
        "first",
        "second",
        "latest",
    )
    assert tuple(message.role.value for message in messages) == (
        "user",
        "assistant",
        "user",
    )


def test_service_does_not_mutate_history() -> None:
    history = [{"role": "user", "content": "original"}]
    service = ModelPipelineService(pipeline=FakePipeline())

    invoke(service, conversation_history=history)

    assert history == [{"role": "user", "content": "original"}]


def test_result_is_immutable() -> None:
    result = invoke(ModelPipelineService(pipeline=FakePipeline()))

    with pytest.raises(ValidationError):
        result.content = "changed"


@pytest.mark.parametrize("message", ["", "   "])
def test_empty_current_user_message_is_rejected(message: str) -> None:
    pipeline = FakePipeline()

    with pytest.raises(ValidationError):
        invoke(
            ModelPipelineService(pipeline=pipeline),
            current_user_message=message,
        )

    assert pipeline.calls == []


@pytest.mark.parametrize("conversation_id", [None, "not-a-uuid", 123])
def test_invalid_conversation_identity_is_rejected(
    conversation_id: object,
) -> None:
    service = ModelPipelineService(pipeline=FakePipeline())

    with pytest.raises(ModelPipelineServiceInputError, match="UUID"):
        service.invoke(
            conversation_id=conversation_id,  # type: ignore[arg-type]
            current_user_message="hello",
            system_instructions="instructions",
            trusted_identity=_identity(),
        )


def _identity() -> TrustedCustomerIdentity:
    now = datetime.now(timezone.utc)
    return TrustedCustomerIdentity(
        customer_id=uuid4(),
        authenticated_at=now,
        expires_at=now + timedelta(hours=1),
        authentication_method="test",
    )


def test_unauthenticated_service_invocation_is_rejected() -> None:
    with pytest.raises(ModelPipelineServiceInputError, match="authenticated"):
        ModelPipelineService(pipeline=FakePipeline()).invoke(
            conversation_id=uuid4(),
            current_user_message="hello",
            system_instructions="instructions",
            trusted_identity=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "history",
    [
        [{"role": "invalid", "content": "message"}],
        [{"role": "user", "content": ""}],
        [{"content": "missing role"}],
        "not-history",
    ],
)
def test_invalid_history_is_rejected(history: object) -> None:
    pipeline = FakePipeline()

    with pytest.raises((ValidationError, TypeError)):
        invoke(
            ModelPipelineService(pipeline=pipeline),
            conversation_history=history,
        )

    assert pipeline.calls == []


def test_context_builder_failure_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = RuntimeError("context failed")

    def fail(**kwargs: object):
        raise expected

    monkeypatch.setattr(model_pipeline_service.ContextBuilder, "build", fail)

    with pytest.raises(RuntimeError) as captured:
        invoke(ModelPipelineService(pipeline=FakePipeline()))

    assert captured.value is expected


def test_pipeline_construction_failure_is_preserved() -> None:
    expected = RuntimeError("startup failed")

    def fail_factory():
        raise expected

    service = ModelPipelineService(pipeline_factory=fail_factory)

    with pytest.raises(RuntimeError) as captured:
        invoke(service)

    assert captured.value is expected


def test_coordinator_failure_is_preserved_without_retry() -> None:
    expected = RuntimeError("provider failed")
    pipeline = FakePipeline(error=expected)

    with pytest.raises(RuntimeError) as captured:
        invoke(ModelPipelineService(pipeline=pipeline))

    assert captured.value is expected
    assert len(pipeline.calls) == 1


def test_direct_dependency_injection_does_not_call_factory() -> None:
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("factory must not be called")

    pipeline = FakePipeline()
    service = ModelPipelineService(
        pipeline=pipeline, pipeline_factory=factory
    )

    invoke(service)

    assert factory_calls == 0
    assert len(pipeline.calls) == 1


def test_lazy_factory_is_called_once_per_service_invocation() -> None:
    pipeline = FakePipeline()
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return pipeline

    service = ModelPipelineService(pipeline_factory=factory)

    invoke(service)

    assert factory_calls == 1
    assert len(pipeline.calls) == 1


def test_invalid_pipeline_or_response_contract_fails_clearly() -> None:
    service = ModelPipelineService(pipeline=object())  # type: ignore[arg-type]
    with pytest.raises(ModelPipelineServiceConfigurationError, match="run"):
        invoke(service)

    pipeline = FakePipeline()
    pipeline.response = {"content": "invalid"}  # type: ignore[assignment]
    with pytest.raises(ModelPipelineServiceConfigurationError, match="ModelResponse"):
        invoke(ModelPipelineService(pipeline=pipeline))


def test_service_construction_has_no_external_side_effect() -> None:
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return FakePipeline()

    service = ModelPipelineService(pipeline_factory=factory)

    assert factory_calls == 0
    assert service._pipeline is None
