"""Route tests for the Stage 7.13 model invocation HTTP boundary."""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

import pytest

from app.api.dependencies import (
    DEFAULT_MODEL_SYSTEM_INSTRUCTIONS,
    get_model_invocation_mapper,
)
from app.api.model_invocation import ModelInvocationMapper
from app.harness import ModelRunPersistenceError, ModelPipelineStartupError
from app.main import app
from app.providers.ollama_qwen import (
    EmptyModelResponseError,
    OllamaRequestTimeoutError,
    OllamaUnavailableError,
)
from app.schemas import ModelInvocationResponse
from app.services import (
    ModelPipelineServiceInputError,
    ModelPipelineServiceResult,
)


class FakeMapper:
    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.calls = []

    def invoke(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return ModelInvocationResponse(
            content="HTTP response",
            provider_name="ollama",
            model_name="qwen3:8b",
        )


class CapturingService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def invoke(self, **kwargs: object) -> ModelPipelineServiceResult:
        self.calls.append(kwargs)
        return ModelPipelineServiceResult(
            content="mapped response",
            provider_name="ollama",
            model_name="qwen3:8b",
        )


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "conversation_id": str(uuid4()),
        "current_user_message": "Where is my order?",
        "conversation_history": [
            {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"},
        ],
    }
    payload.update(overrides)
    return payload


def override_mapper(mapper) -> None:
    app.dependency_overrides[get_model_invocation_mapper] = lambda: mapper


def test_success_response_and_mapper_invoked_exactly_once(api_client) -> None:
    mapper = FakeMapper()
    conversation_id = uuid4()
    override_mapper(mapper)

    response = api_client.post(
        "/api/v1/model/invoke",
        json=valid_payload(conversation_id=str(conversation_id)),
    )

    assert response.status_code == 200
    assert response.json() == {
        "content": "HTTP response",
        "provider_name": "ollama",
        "model_name": "qwen3:8b",
    }
    assert len(mapper.calls) == 1
    request = mapper.calls[0]
    assert request.conversation_id == conversation_id
    assert request.current_user_message == "Where is my order?"
    assert tuple(message.content for message in request.conversation_history) == (
        "Previous question",
        "Previous answer",
    )


def test_default_and_custom_system_instruction_behavior(api_client) -> None:
    service = CapturingService()
    mapper = ModelInvocationMapper(
        service=service,
        default_system_instructions=DEFAULT_MODEL_SYSTEM_INSTRUCTIONS,
    )
    override_mapper(mapper)

    default_response = api_client.post(
        "/api/v1/model/invoke", json=valid_payload()
    )
    custom_response = api_client.post(
        "/api/v1/model/invoke",
        json=valid_payload(system_instructions="Use this instruction."),
    )

    assert default_response.status_code == custom_response.status_code == 200
    assert service.calls[0]["system_instructions"] == (
        DEFAULT_MODEL_SYSTEM_INSTRUCTIONS
    )
    assert service.calls[1]["system_instructions"] == "Use this instruction."
    assert len(service.calls) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"current_user_message": "missing conversation"},
        valid_payload(conversation_id="invalid"),
        valid_payload(current_user_message=" "),
        valid_payload(conversation_history=[{"role": "invalid", "content": "x"}]),
    ],
)
def test_pydantic_request_validation_returns_422(api_client, payload) -> None:
    mapper = FakeMapper()
    override_mapper(mapper)

    response = api_client.post("/api/v1/model/invoke", json=payload)

    assert response.status_code == 422
    assert mapper.calls == []


@pytest.mark.parametrize(
    ("error", "status", "code", "message"),
    [
        (
            ModelPipelineServiceInputError("invalid conversation"),
            400,
            "invalid_application_input",
            "The model invocation input is invalid.",
        ),
        (
            ModelPipelineStartupError("secret configuration failure"),
            503,
            "model_service_unavailable",
            "The model service is temporarily unavailable.",
        ),
        (
            OllamaUnavailableError("secret Ollama transport detail"),
            503,
            "provider_unavailable",
            "The model provider is temporarily unavailable.",
        ),
        (
            OllamaRequestTimeoutError("secret timeout detail"),
            503,
            "provider_unavailable",
            "The model provider is temporarily unavailable.",
        ),
        (
            EmptyModelResponseError("secret raw response"),
            502,
            "invalid_provider_response",
            "The model provider returned an invalid response.",
        ),
        (
            ModelRunPersistenceError("secret database URL"),
            500,
            "model_run_persistence_failed",
            "The model invocation could not be recorded.",
        ),
        (
            RuntimeError("secret internal stack detail"),
            500,
            "internal_error",
            "The model invocation failed unexpectedly.",
        ),
    ],
)
def test_known_and_unexpected_errors_map_to_safe_stable_responses(
    api_client, error, status, code, message
) -> None:
    mapper = FakeMapper(error=error)
    override_mapper(mapper)

    response = api_client.post("/api/v1/model/invoke", json=valid_payload())

    assert response.status_code == status
    assert response.json() == {"code": code, "message": message}
    assert len(mapper.calls) == 1
    assert "secret" not in response.text.lower()
    assert "postgresql://" not in response.text
    assert "traceback" not in response.text.lower()


def test_dependency_override_does_not_construct_real_runtime(api_client) -> None:
    mapper = FakeMapper()
    override_mapper(mapper)

    response = api_client.post("/api/v1/model/invoke", json=valid_payload())

    assert response.status_code == 200
    assert len(mapper.calls) == 1


def test_openapi_registers_request_response_and_documented_errors(api_client) -> None:
    schema = api_client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/model/invoke"]["post"]

    assert operation["tags"] == ["Model Invocation"]
    assert operation["summary"] == "Invoke the configured customer-service model"
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ModelInvocationRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ModelInvocationResponse"}
    assert {"400", "422", "500", "502", "503"}.issubset(
        operation["responses"]
    )
    assert operation["responses"]["503"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/APIErrorResponse"}
