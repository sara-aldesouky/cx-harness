"""Focused Stage 14 provider-neutral orchestration tests."""

from __future__ import annotations

from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError as FutureCancelledError
import inspect
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.model_orchestration import (
    AvailableModelTool,
    DuplicateModelAdapterError,
    FakeModelProviderAdapter,
    ModelAdapterNotFoundError,
    ModelExecutionMetadata,
    ModelFinishReason,
    ModelGenerationSettings,
    ModelMessage,
    ModelMessageRole,
    ModelOrchestrationError,
    ModelOrchestrationRequest,
    ModelOrchestrationResponse,
    ModelOrchestrator,
    ModelOrchestratorConfiguration,
    ModelProviderAdapter,
    ModelProviderAdapterError,
    ModelProviderAdapterRegistry,
    ModelProviderCapabilities,
    ModelResponseMetadata,
    NormalizedToolSelection,
    ProviderFailureCategory,
)
from app.model_orchestration import adapter as adapter_module
from app.model_orchestration import orchestrator as orchestrator_module


REQUEST_ID = UUID("00000000-0000-0000-0000-000000000001")
TRACE_ID = UUID("00000000-0000-0000-0000-000000000002")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000003")


def request() -> ModelOrchestrationRequest:
    return ModelOrchestrationRequest(
        system_instructions="  Be concise and accurate.  ",
        messages=(
            ModelMessage(role=ModelMessageRole.USER, content="  Where is it?  "),
        ),
        available_tools=(
            AvailableModelTool(
                name="order_status",
                version="1.0.0",
                description="Read an order status.",
                input_schema={
                    "type": "object",
                    "properties": {"order_number": {"type": "string"}},
                },
            ),
        ),
        generation=ModelGenerationSettings(
            temperature=0.2,
            max_output_tokens=128,
            top_p=0.9,
            stop_sequences=("DONE",),
        ),
        execution=ModelExecutionMetadata(
            request_id=REQUEST_ID,
            correlation_id=TRACE_ID,
            conversation_id=CONVERSATION_ID,
            attributes={"source": "test"},
        ),
    )


def response(
    provider: str = "alpha",
    model: str = "model-a",
    *,
    tool_calls: bool = False,
) -> ModelOrchestrationResponse:
    selections = (
        NormalizedToolSelection(
            call_id="call-001",
            tool_name="order_status",
            tool_version="1.0.0",
            arguments={"order_number": "PROVIDER-SUGGESTED"},
        ),
    ) if tool_calls else ()
    return ModelOrchestrationResponse(
        assistant_message=(
            None
            if tool_calls
            else ModelMessage(
                role=ModelMessageRole.ASSISTANT,
                content="A normalized response.",
            )
        ),
        tool_selections=selections,
        metadata=ModelResponseMetadata(
            provider_name=provider,
            model_identifier=model,
            request_id="provider-request-001",
            latency_ms=999,
            input_tokens=10,
            output_tokens=4,
            total_tokens=14,
            finish_reason=(
                ModelFinishReason.TOOL_CALLS
                if tool_calls
                else ModelFinishReason.STOP
            ),
        ),
        provider_metadata={"region": "local", "nested": {"attempt": 1}},
    )


class ScriptedAdapter(ModelProviderAdapter):
    def __init__(
        self,
        provider: str,
        model: str,
        outcome,
    ) -> None:  # type: ignore[no-untyped-def]
        self._provider = provider
        self._model = model
        self.outcome = outcome
        self.requests = []

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model_identifier(self) -> str:
        return self._model

    def invoke(self, model_request):  # type: ignore[no-untyped-def]
        self.requests.append(model_request)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def orchestrator(adapter: ModelProviderAdapter, *, clock=lambda: 1.0):
    registry = ModelProviderAdapterRegistry()
    registry.register(adapter)
    return ModelOrchestrator(
        registry,
        ModelOrchestratorConfiguration(
            provider_name=adapter.provider_name,
            model_identifier=adapter.model_identifier,
        ),
        clock=clock,
    )


def test_request_contract_normalizes_and_serializes_deterministically() -> None:
    model_request = request()
    assert model_request.system_instructions == "Be concise and accurate."
    assert model_request.messages[0].content == "Where is it?"
    serialized = model_request.model_dump_json()
    assert serialized == model_request.model_dump_json()
    assert ModelOrchestrationRequest.model_validate_json(serialized) == model_request


def test_contracts_are_deeply_immutable_and_defensively_copied() -> None:
    source = {"type": "object", "properties": {"value": {"type": "string"}}}
    tool = AvailableModelTool(
        name="sample",
        version="1.0.0",
        description="Sample tool.",
        input_schema=source,
    )
    source["properties"]["value"]["type"] = "integer"
    assert tool.input_schema["properties"]["value"]["type"] == "string"
    with pytest.raises(TypeError):
        tool.input_schema["new"] = "value"  # type: ignore[index]
    with pytest.raises(ValidationError):
        tool.name = "changed"  # type: ignore[misc]


def test_response_preserves_ordered_structured_tool_selection_exactly() -> None:
    adapter = ScriptedAdapter("alpha", "model-a", response(tool_calls=True))
    result = orchestrator(adapter).orchestrate(request())
    assert result.tool_selections[0].model_dump(mode="json") == {
        "call_id": "call-001",
        "tool_name": "order_status",
        "tool_version": "1.0.0",
        "arguments": {"order_number": "PROVIDER-SUGGESTED"},
    }
    assert adapter.requests == [request()]


def test_orchestrator_records_normalized_total_latency() -> None:
    ticks = iter((10.0, 10.125))
    result = orchestrator(
        ScriptedAdapter("alpha", "model-a", response()),
        clock=lambda: next(ticks),
    ).orchestrate(request())
    assert result.metadata.latency_ms == 125
    assert result.metadata.input_tokens == 10
    assert result.metadata.output_tokens == 4
    assert result.metadata.total_tokens == 14


def test_fake_adapter_is_deterministic_and_network_free() -> None:
    adapter = FakeModelProviderAdapter()
    service = orchestrator(adapter)
    first = service.orchestrate(request())
    second = service.orchestrate(request())
    assert first == second
    assert first.assistant_message.content == "Fake response: Where is it?"
    assert first.metadata.provider_name == "fake"
    assert first.metadata.model_identifier == "fake-model-v1"
    assert adapter.supports_streaming is False


def test_provider_capabilities_are_immutable_neutral_and_extensible() -> None:
    class CapableAdapter(ScriptedAdapter):
        @property
        def capabilities(self) -> ModelProviderCapabilities:
            return ModelProviderCapabilities(
                tool_calling=True,
                streaming=True,
                structured_output=True,
                system_instructions=True,
                image_input=True,
                multimodal_input=True,
                function_calling=True,
            )

    adapter = CapableAdapter("alpha", "model-a", response())
    assert adapter.capabilities.model_dump() == {
        "tool_calling": True,
        "streaming": True,
        "structured_output": True,
        "system_instructions": True,
        "image_input": True,
        "multimodal_input": True,
        "function_calling": True,
    }
    assert adapter.supports_streaming is True
    with pytest.raises(ValidationError):
        adapter.capabilities.streaming = False  # type: ignore[misc]


@pytest.mark.parametrize(
    "cancellation", [AsyncCancelledError(), FutureCancelledError()]
)
def test_cancellation_propagates_without_provider_failure_normalization(
    cancellation,
) -> None:
    adapter = ScriptedAdapter("alpha", "model-a", cancellation)
    with pytest.raises(type(cancellation)):
        orchestrator(adapter).orchestrate(request())
    assert len(adapter.requests) == 1


def test_provider_switching_requires_only_configuration_and_registration() -> None:
    registry = ModelProviderAdapterRegistry()
    alpha = ScriptedAdapter("alpha", "model-a", response("alpha", "model-a"))
    beta = ScriptedAdapter("beta", "model-b", response("beta", "model-b"))
    registry.register(alpha)
    registry.register(beta)

    alpha_result = ModelOrchestrator(
        registry, ModelOrchestratorConfiguration(provider_name="ALPHA", model_identifier="model-a")
    ).orchestrate(request())
    beta_result = ModelOrchestrator(
        registry, ModelOrchestratorConfiguration(provider_name="beta", model_identifier="model-b")
    ).orchestrate(request())

    assert alpha_result.metadata.provider_name == "alpha"
    assert beta_result.metadata.provider_name == "beta"
    assert registry.providers() == ("alpha", "beta")


@pytest.mark.parametrize("category", tuple(ProviderFailureCategory))
def test_adapter_failures_are_normalized_without_leaking_provider_exception(
    category,
) -> None:
    adapter = ScriptedAdapter(
        "alpha",
        "model-a",
        ModelProviderAdapterError(category, "Safe provider failure.", retryable=True),
    )
    with pytest.raises(ModelOrchestrationError) as raised:
        orchestrator(adapter).orchestrate(request())
    assert raised.value.category is category
    assert raised.value.public_message == "Safe provider failure."
    assert raised.value.retryable is True


def test_unexpected_adapter_exception_is_safely_normalized() -> None:
    adapter = ScriptedAdapter("alpha", "model-a", RuntimeError("SDK SECRET"))
    with pytest.raises(ModelOrchestrationError) as raised:
        orchestrator(adapter).orchestrate(request())
    assert raised.value.category is ProviderFailureCategory.EXECUTION_FAILURE
    assert "SDK SECRET" not in str(raised.value)


@pytest.mark.parametrize(
    "outcome",
    [object(), response("wrong", "model-a"), response("alpha", "wrong-model")],
)
def test_malformed_or_inconsistent_provider_responses_fail_closed(outcome) -> None:
    adapter = ScriptedAdapter("alpha", "model-a", outcome)
    with pytest.raises(ModelOrchestrationError) as raised:
        orchestrator(adapter).orchestrate(request())
    assert raised.value.category is ProviderFailureCategory.MALFORMED_RESPONSE


def test_constructed_invalid_provider_contract_is_normalized() -> None:
    malformed = ModelOrchestrationResponse.model_construct(
        assistant_message=None,
        tool_selections=(),
        metadata=response().metadata,
        provider_metadata={},
    )
    with pytest.raises(ModelOrchestrationError) as raised:
        orchestrator(
            ScriptedAdapter("alpha", "model-a", malformed)
        ).orchestrate(request())
    assert raised.value.category is ProviderFailureCategory.MALFORMED_RESPONSE


def test_configured_adapter_identity_mismatch_fails_before_invocation() -> None:
    registry = ModelProviderAdapterRegistry()
    adapter = ScriptedAdapter("alpha", "actual-model", response("alpha", "actual-model"))
    registry.register(adapter)
    service = ModelOrchestrator(
        registry,
        ModelOrchestratorConfiguration(
            provider_name="alpha", model_identifier="configured-model"
        ),
    )
    with pytest.raises(ModelOrchestrationError) as raised:
        service.orchestrate(request())
    assert raised.value.category is ProviderFailureCategory.MALFORMED_RESPONSE
    assert adapter.requests == []


def test_unknown_configured_provider_is_normalized_as_unavailable() -> None:
    service = ModelOrchestrator(
        ModelProviderAdapterRegistry(),
        ModelOrchestratorConfiguration(
            provider_name="missing", model_identifier="model"
        ),
    )
    with pytest.raises(ModelOrchestrationError) as raised:
        service.orchestrate(request())
    assert raised.value.category is ProviderFailureCategory.UNAVAILABLE
    assert raised.value.retryable is True


def test_registry_is_deterministic_and_rejects_duplicates() -> None:
    registry = ModelProviderAdapterRegistry()
    registry.register(FakeModelProviderAdapter(provider_name="beta"))
    registry.register(FakeModelProviderAdapter(provider_name="alpha"))
    assert registry.has(" ALPHA ") is True
    assert registry.providers() == ("alpha", "beta")
    with pytest.raises(DuplicateModelAdapterError):
        registry.register(FakeModelProviderAdapter(provider_name="Alpha"))
    with pytest.raises(ModelAdapterNotFoundError):
        registry.get("missing")


def test_runtime_and_adapter_dependency_direction_remains_one_way() -> None:
    adapter_source = inspect.getsource(adapter_module)
    orchestrator_source = inspect.getsource(orchestrator_module)
    forbidden = (
        "app.harness",
        "app.services",
        "app.tools",
        "google.generativeai",
        "ollama",
        "openai",
        "anthropic",
    )
    assert all(name not in adapter_source for name in forbidden)
    assert all(name not in orchestrator_source for name in forbidden)


@pytest.mark.parametrize(
    "role", [ModelMessageRole.ASSISTANT, ModelMessageRole.USER]
)
def test_non_tool_messages_reject_tool_correlation(role) -> None:
    with pytest.raises(ValidationError):
        ModelMessage(
            role=role,
            content="message",
            tool_call_id="call-001",
        )


def test_response_and_usage_contracts_reject_inconsistent_shapes() -> None:
    with pytest.raises(ValidationError):
        ModelResponseMetadata(
            provider_name="alpha",
            model_identifier="model-a",
            request_id="request",
            latency_ms=1,
            input_tokens=2,
            output_tokens=3,
            total_tokens=99,
            finish_reason=ModelFinishReason.STOP,
        )
    with pytest.raises(ValidationError):
        ModelOrchestrationResponse.model_validate(
            {
                **response().model_dump(mode="python"),
                "tool_selections": response(tool_calls=True).tool_selections,
            }
        )


def test_public_boundaries_reject_untyped_dependencies_and_requests() -> None:
    with pytest.raises(TypeError):
        ModelProviderAdapterRegistry().register(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ModelOrchestrator(object(), ModelOrchestratorConfiguration(provider_name="a", model_identifier="m"))  # type: ignore[arg-type]
    service = orchestrator(FakeModelProviderAdapter())
    with pytest.raises(TypeError):
        service.orchestrate(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ModelMessage(role=ModelMessageRole.USER, content=" "),
        lambda: ModelMessage(role=ModelMessageRole.TOOL, content="result"),
        lambda: AvailableModelTool(
            name=" ", version="1", description="tool", input_schema={"type": "object"}
        ),
        lambda: AvailableModelTool(
            name="tool", version="1", description="tool", input_schema={}
        ),
        lambda: ModelGenerationSettings(temperature=-0.1),
        lambda: ModelGenerationSettings(max_output_tokens=0),
        lambda: ModelGenerationSettings(top_p=0),
        lambda: ModelGenerationSettings(stop_sequences=(" ",)),
        lambda: ModelGenerationSettings(stop_sequences=("END", "END")),
        lambda: NormalizedToolSelection(
            call_id=" ", tool_name="tool", arguments={}
        ),
        lambda: ModelResponseMetadata(
            provider_name=" ", model_identifier="model", request_id="request",
            latency_ms=0, input_tokens=0, output_tokens=0, total_tokens=0,
            finish_reason=ModelFinishReason.STOP,
        ),
        lambda: ModelResponseMetadata(
            provider_name="provider", model_identifier="model", request_id="request",
            latency_ms=-1, input_tokens=0, output_tokens=0, total_tokens=0,
            finish_reason=ModelFinishReason.STOP,
        ),
    ],
)
def test_contract_validation_rejects_malformed_values(factory) -> None:
    with pytest.raises((ValidationError, ValueError)):
        factory()


def test_request_rejects_empty_messages_and_duplicate_tools() -> None:
    base = request().model_dump(mode="python")
    with pytest.raises(ValidationError):
        ModelOrchestrationRequest.model_validate({**base, "messages": ()})
    duplicate = request().available_tools * 2
    with pytest.raises(ValidationError):
        ModelOrchestrationRequest.model_validate(
            {**base, "available_tools": duplicate}
        )
    with pytest.raises(ValidationError):
        ModelOrchestrationRequest.model_validate(
            {**base, "system_instructions": " "}
        )


def test_response_rejects_empty_duplicate_and_wrong_role_shapes() -> None:
    metadata = response().metadata
    selection = response(tool_calls=True).tool_selections[0]
    with pytest.raises(ValidationError):
        ModelOrchestrationResponse(metadata=metadata)
    with pytest.raises(ValidationError):
        ModelOrchestrationResponse(
            tool_selections=(selection, selection),
            metadata=response(tool_calls=True).metadata,
        )
    with pytest.raises(ValidationError):
        ModelOrchestrationResponse(
            assistant_message=ModelMessage(
                role=ModelMessageRole.USER, content="not an assistant"
            ),
            metadata=metadata,
        )
    with pytest.raises(ValidationError):
        ModelOrchestrationResponse(
            assistant_message=ModelMessage(
                role=ModelMessageRole.ASSISTANT, content="missing calls"
            ),
            metadata=response(tool_calls=True).metadata,
        )


def test_json_contracts_reject_non_json_values_and_freeze_lists() -> None:
    execution = ModelExecutionMetadata(
        request_id=REQUEST_ID,
        correlation_id=TRACE_ID,
        attributes={"items": ["one", "two"]},
    )
    assert execution.attributes["items"] == ("one", "two")
    assert execution.model_dump(mode="json")["attributes"]["items"] == ["one", "two"]
    with pytest.raises(ValidationError):
        ModelExecutionMetadata(
            request_id=REQUEST_ID,
            correlation_id=TRACE_ID,
            attributes={"invalid": object()},
        )


def test_adapter_registry_configuration_and_fake_validation_fail_fast() -> None:
    with pytest.raises(ValueError):
        ModelProviderAdapterError(ProviderFailureCategory.TIMEOUT, " ")
    with pytest.raises(ValueError):
        FakeModelProviderAdapter(provider_name=" ")
    with pytest.raises(TypeError):
        FakeModelProviderAdapter().invoke(object())  # type: ignore[arg-type]
    registry = ModelProviderAdapterRegistry()
    with pytest.raises(TypeError):
        registry.has(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        registry.get(" ")
    with pytest.raises(ValidationError):
        ModelOrchestratorConfiguration(provider_name=" ", model_identifier="model")
    with pytest.raises(ValidationError):
        ModelOrchestratorConfiguration(provider_name="provider", model_identifier=" ")
    with pytest.raises(TypeError):
        ModelOrchestrator(
            registry,
            object(),  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        ModelOrchestrator(
            registry,
            ModelOrchestratorConfiguration(
                provider_name="provider", model_identifier="model"
            ),
            clock=object(),  # type: ignore[arg-type]
        )
