"""Tests for Stage 7.12 public model-invocation contracts and mapping."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.api.model_invocation import ModelInvocationMapper
from app.authentication import TrustedCustomerIdentity
from app.harness import ConversationMessage
from app.schemas import (
    ModelInvocationHistoryMessage,
    ModelInvocationRequest,
    ModelInvocationResponse,
)
from app.services import ModelPipelineServiceResult


class FakeService:
    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def invoke(self, **kwargs: object) -> ModelPipelineServiceResult:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return ModelPipelineServiceResult(
            content="service response",
            provider_name="ollama",
            model_name="qwen3:8b",
        )


def make_request(**overrides: object) -> ModelInvocationRequest:
    values = {
        "conversation_id": uuid4(),
        "current_user_message": " Current question ",
        "conversation_history": [
            {"role": "user", "content": " first "},
            {"role": "assistant", "content": " second "},
        ],
    }
    values.update(overrides)
    return ModelInvocationRequest(**values)


def identity() -> TrustedCustomerIdentity:
    now = datetime.now(timezone.utc)
    return TrustedCustomerIdentity(
        customer_id=uuid4(),
        authenticated_at=now,
        expires_at=now + timedelta(hours=1),
        authentication_method="test",
    )


def test_valid_request_parsing_normalization_and_ordering() -> None:
    conversation_id = uuid4()
    request = make_request(
        conversation_id=str(conversation_id),
        system_instructions=" Be concise. ",
    )

    assert request.conversation_id == conversation_id
    assert request.current_user_message == "Current question"
    assert request.system_instructions == "Be concise."
    assert tuple(message.content for message in request.conversation_history) == (
        "first",
        "second",
    )


@pytest.mark.parametrize("conversation_id", ["not-a-uuid", "", 123])
def test_invalid_uuid_is_rejected(conversation_id: object) -> None:
    with pytest.raises(ValidationError):
        make_request(conversation_id=conversation_id)


@pytest.mark.parametrize("message", ["", "   "])
def test_empty_current_message_is_rejected(message: str) -> None:
    with pytest.raises(ValidationError):
        make_request(current_user_message=message)


@pytest.mark.parametrize(
    "history",
    [
        [{"role": "invalid", "content": "message"}],
        [{"role": "user", "content": ""}],
        [{"content": "missing role"}],
    ],
)
def test_invalid_history_or_role_is_rejected(history: object) -> None:
    with pytest.raises(ValidationError):
        make_request(conversation_history=history)


def test_history_schema_exposes_only_role_and_content() -> None:
    with pytest.raises(ValidationError):
        ModelInvocationHistoryMessage(
            role="user",
            content="hello",
            metadata={"internal": "hidden"},
        )


@pytest.mark.parametrize("instructions", ["", "   "])
def test_blank_optional_system_instructions_are_rejected(
    instructions: str,
) -> None:
    with pytest.raises(ValidationError):
        make_request(system_instructions=instructions)


def test_request_to_service_mapping_preserves_all_supported_inputs() -> None:
    service = FakeService()
    conversation_id = uuid4()
    request = make_request(
        conversation_id=conversation_id,
        system_instructions="Custom instructions",
    )

    response = ModelInvocationMapper(
        service=service,
        default_system_instructions="Default instructions",
    ).invoke(request, identity())

    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["conversation_id"] == conversation_id
    assert call["current_user_message"] == "Current question"
    assert call["system_instructions"] == "Custom instructions"
    assert isinstance(call["trusted_identity"], TrustedCustomerIdentity)
    history = call["conversation_history"]
    assert isinstance(history, tuple)
    assert all(isinstance(message, ConversationMessage) for message in history)
    assert tuple(message.content for message in history) == ("first", "second")
    assert response == ModelInvocationResponse(
        content="service response",
        provider_name="ollama",
        model_name="qwen3:8b",
    )


def test_optional_instructions_use_injected_default() -> None:
    service = FakeService()

    ModelInvocationMapper(
        service=service,
        default_system_instructions=" Configured default ",
    ).invoke(make_request(), identity())

    assert service.calls[0]["system_instructions"] == "Configured default"


def test_service_result_to_response_mapping_and_serialization() -> None:
    result = ModelPipelineServiceResult(
        content=" answer ", provider_name=" ollama ", model_name=" qwen3:8b "
    )

    response = ModelInvocationMapper.to_response(result)

    assert response.model_dump(mode="json") == {
        "content": "answer",
        "provider_name": "ollama",
        "model_name": "qwen3:8b",
    }
    assert json.loads(response.model_dump_json()) == response.model_dump(
        mode="json"
    )


def test_request_and_response_are_immutable() -> None:
    request = make_request()
    response = ModelInvocationResponse(
        content="answer", provider_name="ollama", model_name="qwen3:8b"
    )

    with pytest.raises(ValidationError):
        request.current_user_message = "changed"
    with pytest.raises(ValidationError):
        response.content = "changed"


def test_application_service_exception_is_preserved() -> None:
    expected = RuntimeError("provider failed")
    mapper = ModelInvocationMapper(
        service=FakeService(error=expected),
        default_system_instructions="instructions",
    )

    with pytest.raises(RuntimeError) as captured:
        mapper.invoke(make_request(), identity())

    assert captured.value is expected


def test_mapper_rejects_invalid_dependencies_and_contract_types() -> None:
    with pytest.raises(TypeError, match="service"):
        ModelInvocationMapper(
            service=object(),  # type: ignore[arg-type]
            default_system_instructions="instructions",
        )
    with pytest.raises(ValueError, match="default_system_instructions"):
        ModelInvocationMapper(
            service=FakeService(), default_system_instructions=" "
        )
    mapper = ModelInvocationMapper(
        service=FakeService(), default_system_instructions="instructions"
    )
    with pytest.raises(TypeError, match="ModelInvocationRequest"):
        mapper.invoke({}, identity())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TrustedCustomerIdentity"):
        mapper.invoke(make_request(), object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ModelPipelineServiceResult"):
        mapper.to_response(object())  # type: ignore[arg-type]


def test_request_forbids_unsupported_external_fields() -> None:
    with pytest.raises(ValidationError):
        ModelInvocationRequest(
            conversation_id=uuid4(),
            current_user_message="hello",
            provider_name="ollama",
        )
