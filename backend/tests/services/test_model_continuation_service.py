"""Tests for exactly one terminal model continuation invocation."""

import inspect
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ConfigDict, ValidationError

from app.harness.context import (
    ConversationContext,
    ConversationMessage,
    ConversationRole,
)
from app.providers import (
    ModelContinuationNotSupportedError,
    ModelProvider,
    ModelResponse,
    ProviderCapabilities,
    ProviderRegistry,
)
from app.services import (
    AdditionalToolCallNotSupportedError,
    InvalidModelContinuationInputError,
    InvalidModelContinuationResponseError,
    ModelContinuationInvocationError,
    ModelContinuationModelMismatchError,
    ModelContinuationProviderMismatchError,
    ModelContinuationRequest,
    ModelContinuationRequestCreationError,
    SingleModelContinuationService,
)
from app.services import model_continuation_service as service_module
from app.tools import (
    ExecutionContext,
    MockProviderContinuationAdapter,
    MockProviderToolCallAdapter,
    PingTool,
    ProviderContinuationAdapterRegistry,
    ProviderContinuationPayload,
    ProviderToolCallAdapterRegistry,
    SingleProviderToolCallCycleService,
    ToolContinuationCycle,
    ToolExecutionOutcome,
    ToolExecutionRequest,
    ToolRegistry,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ToolSelectionService,
    ValidatedToolSelection,
    build_tool_continuation_runtime,
)
from tests.tools.audit_fakes import RecordingAuditRepository


def conversation_context(
    provider_name: str = "mock", model_name: str = "mock-model"
) -> ConversationContext:
    return ConversationContext(
        system_instructions="Answer after receiving the tool result.",
        messages=(
            ConversationMessage(
                role=ConversationRole.USER,
                content="Ping the system.",
            ),
        ),
        provider_name=provider_name,
        model_name=model_name,
    )


def completed_cycle() -> tuple[ToolContinuationCycle, RecordingAuditRepository]:
    tools = ToolRegistry()
    tools.register(PingTool)
    call_adapters = ProviderToolCallAdapterRegistry()
    call_adapters.register("mock", MockProviderToolCallAdapter())
    selection_service = ToolSelectionService(
        call_adapters, ToolSelectionResolver(tools)
    )
    continuation_adapters = ProviderContinuationAdapterRegistry()
    continuation_adapters.register("mock", MockProviderContinuationAdapter())
    audit = RecordingAuditRepository()
    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuation_adapters,
        audit_repository=audit,
    )
    provider_cycle = SingleProviderToolCallCycleService(
        selection_service, runtime
    )
    cycle = provider_cycle.run(
        "mock",
        {
            "tool_calls": [
                {
                    "id": "call-001",
                    "name": "ping",
                    "version": "1.0.0",
                    "arguments": {"message": "hello"},
                }
            ]
        },
        ExecutionContext(trace_id=uuid4(), execution_id=uuid4()),
    )
    return cycle, audit


_DEFAULT_RESPONSE = object()


class FakeContinuationProvider(ModelProvider):
    def __init__(
        self,
        *,
        provider_name: str = "mock",
        model_name: str = "mock-model",
        response: Any = _DEFAULT_RESPONSE,
        error: Exception = None,
    ) -> None:
        self._provider_name = provider_name
        self._model_name = model_name
        self.response = response
        self.error = error
        self.calls = 0
        self.requests: list[ModelContinuationRequest] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def generate(self, request: Any) -> ModelResponse:
        raise AssertionError("initial model invocation is outside this service")

    def continue_model(self, request: ModelContinuationRequest) -> ModelResponse:
        self.calls += 1
        self.requests.append(request)
        if self.error:
            raise self.error
        if self.response is not _DEFAULT_RESPONSE:
            return self.response
        return ModelResponse(
            content="Final answer after ping.",
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


def build_service(provider: ModelProvider) -> SingleModelContinuationService:
    registry = ProviderRegistry()
    registry.register(provider)
    return SingleModelContinuationService(registry)


def test_successful_terminal_continuation_returns_original_response() -> None:
    cycle, audit = completed_cycle()
    response = ModelResponse(
        content="Final answer.", provider_name="mock", model_name="mock-model"
    )
    provider = FakeContinuationProvider(response=response)
    service = build_service(provider)
    context = conversation_context()

    actual = service.continue_once(
        provider_name="mock",
        model_name="mock-model",
        cycle=cycle,
        context=context,
    )

    assert actual is response
    assert provider.calls == 1
    assert len(audit.started) == len(audit.finalized) == 1


def test_provider_normalization_and_exact_payload_context_propagation() -> None:
    cycle, _ = completed_cycle()
    provider = FakeContinuationProvider()
    service = build_service(provider)
    context = conversation_context(provider_name=" MOCK ")

    service.continue_once(
        provider_name="  MoCk  ",
        model_name="mock-model",
        cycle=cycle,
        context=context,
    )

    assert provider.calls == 1
    request = provider.requests[0]
    assert request.provider_name == "mock"
    assert request.model_name == "mock-model"
    assert request.context is context
    assert request.continuation_payload is cycle.continuation_payload


def test_request_contract_is_frozen_and_json_serializable() -> None:
    cycle, _ = completed_cycle()
    request = ModelContinuationRequest(
        provider_name=" mock ",
        model_name="mock-model",
        context=conversation_context(),
        continuation_payload=cycle.continuation_payload,
    )

    assert request.model_dump(mode="json")["continuation_payload"]["call_id"] == "call-001"
    with pytest.raises(ValidationError, match="frozen"):
        request.model_name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_name": " "},
        {"model_name": " "},
        {"provider_name": "gemini"},
        {
            "context": ConversationContext(
                system_instructions="Continue.",
                messages=(ConversationMessage(role=ConversationRole.USER, content="Hi"),),
            )
        },
        {"context": conversation_context(provider_name="gemini")},
        {"context": conversation_context(model_name="other-model")},
    ],
)
def test_request_contract_rejects_invalid_or_mismatched_identity(
    overrides: dict[str, object],
) -> None:
    cycle, _ = completed_cycle()
    values = {
        "provider_name": "mock",
        "model_name": "mock-model",
        "context": conversation_context(),
        "continuation_payload": cycle.continuation_payload,
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        ModelContinuationRequest(**values)


@pytest.mark.parametrize(
    ("provider_name", "model_name"),
    [("", "mock-model"), (" ", "mock-model"), (None, "mock-model"), ("mock", ""), ("mock", " "), ("mock", None)],
)
def test_service_rejects_invalid_provider_or_model_identity(
    provider_name: object, model_name: object,
) -> None:
    cycle, _ = completed_cycle()

    with pytest.raises(InvalidModelContinuationInputError):
        build_service(FakeContinuationProvider()).continue_once(
            provider_name=provider_name,  # type: ignore[arg-type]
            model_name=model_name,  # type: ignore[arg-type]
            cycle=cycle,
            context=conversation_context(),
        )


@pytest.mark.parametrize("provider_name", ["gemini", "ollama"])
def test_requested_provider_mismatch_rejected_before_lookup(provider_name: str) -> None:
    cycle, _ = completed_cycle()
    provider = FakeContinuationProvider()

    with pytest.raises(ModelContinuationProviderMismatchError):
        build_service(provider).continue_once(
            provider_name=provider_name,
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(provider_name=provider_name),
        )

    assert provider.calls == 0


def test_context_provider_mismatch_is_rejected() -> None:
    cycle, _ = completed_cycle()
    provider = FakeContinuationProvider()

    with pytest.raises(ModelContinuationProviderMismatchError):
        build_service(provider).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(provider_name="gemini"),
        )


@pytest.mark.parametrize("requested_model", ["other-model", "mock-model-v2"])
def test_context_model_mismatch_is_rejected(requested_model: str) -> None:
    cycle, _ = completed_cycle()
    provider = FakeContinuationProvider()

    with pytest.raises(ModelContinuationModelMismatchError):
        build_service(provider).continue_once(
            provider_name="mock",
            model_name=requested_model,
            cycle=cycle,
            context=conversation_context(model_name="mock-model"),
        )

    assert provider.calls == 0


def test_resolved_provider_model_mismatch_is_rejected() -> None:
    cycle, _ = completed_cycle()
    provider = FakeContinuationProvider(model_name="different-model")

    with pytest.raises(ModelContinuationModelMismatchError):
        build_service(provider).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )

    assert provider.calls == 0


def test_defective_registry_returning_another_provider_is_rejected() -> None:
    cycle, _ = completed_cycle()
    wrong = FakeContinuationProvider(provider_name="gemini")

    class DefectiveRegistry(ProviderRegistry):
        def get(self, name: str) -> ModelProvider:
            return wrong

    with pytest.raises(ModelContinuationProviderMismatchError):
        SingleModelContinuationService(DefectiveRegistry()).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )

    assert wrong.calls == 0


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        None,
        [],
        (),
        [completed_cycle()[0]],
        completed_cycle()[0].selection,
        completed_cycle()[0].execution_request,
        completed_cycle()[0].execution_outcome,
        completed_cycle()[0].continuation_payload,
    ],
)
def test_completed_cycle_is_required(invalid: object) -> None:
    provider = FakeContinuationProvider()

    with pytest.raises(InvalidModelContinuationInputError):
        build_service(provider).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=invalid,  # type: ignore[arg-type]
            context=conversation_context(),
        )

    assert provider.calls == 0


@pytest.mark.parametrize("invalid", [{}, None, [], "context"])
def test_invalid_continuation_context_is_rejected(invalid: object) -> None:
    cycle, _ = completed_cycle()

    with pytest.raises(InvalidModelContinuationInputError):
        build_service(FakeContinuationProvider()).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=invalid,  # type: ignore[arg-type]
        )


def test_deferred_context_without_model_identity_is_rejected() -> None:
    cycle, _ = completed_cycle()
    deferred = ConversationContext(
        system_instructions="Continue.",
        messages=(ConversationMessage(role=ConversationRole.USER, content="Hello"),),
    )

    with pytest.raises(InvalidModelContinuationInputError):
        build_service(FakeContinuationProvider()).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=deferred,
        )


def test_unknown_provider_is_wrapped_and_never_invoked() -> None:
    cycle, _ = completed_cycle()
    registry = ProviderRegistry()

    with pytest.raises(ModelContinuationInvocationError) as captured:
        SingleModelContinuationService(registry).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )

    assert captured.value.__cause__ is not None


def test_provider_without_continuation_support_fails_explicitly() -> None:
    from app.providers import MockModelProvider

    cycle, _ = completed_cycle()

    with pytest.raises(ModelContinuationInvocationError) as captured:
        build_service(MockModelProvider()).continue_once(
            provider_name="mock",
            model_name="mock-deterministic-v1",
            cycle=cycle,
            context=conversation_context(model_name="mock-deterministic-v1"),
        )

    assert isinstance(captured.value.__cause__, ModelContinuationNotSupportedError)


def test_request_creation_failure_is_wrapped_with_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle, _ = completed_cycle()
    original = ValueError("private request contents")

    def fail(**values: object) -> None:
        raise original

    monkeypatch.setattr(service_module, "ModelContinuationRequest", fail)

    with pytest.raises(ModelContinuationRequestCreationError) as captured:
        build_service(FakeContinuationProvider()).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )

    assert captured.value.__cause__ is original
    assert "private" not in str(captured.value)


class ProviderTimeoutError(TimeoutError):
    pass


class ProviderAuthenticationError(RuntimeError):
    pass


class ProviderRateLimitError(RuntimeError):
    pass


@pytest.mark.parametrize(
    "error",
    [
        ProviderTimeoutError("timeout details"),
        ProviderAuthenticationError("credential details"),
        ProviderRateLimitError("rate response details"),
        RuntimeError("transport response details"),
    ],
)
def test_provider_invocation_failures_are_wrapped_once_with_cause(
    error: Exception,
) -> None:
    cycle, _ = completed_cycle()
    provider = FakeContinuationProvider(error=error)

    with pytest.raises(ModelContinuationInvocationError) as captured:
        build_service(provider).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )

    assert captured.value.__cause__ is error
    assert provider.calls == 1
    assert "details" not in str(captured.value)


@pytest.mark.parametrize("invalid", [None, {}, object()])
def test_noncanonical_provider_responses_are_rejected(invalid: object) -> None:
    cycle, _ = completed_cycle()
    provider = FakeContinuationProvider(response=invalid)

    with pytest.raises(InvalidModelContinuationResponseError):
        build_service(provider).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )

    assert provider.calls == 1


def test_malformed_constructed_response_is_rejected() -> None:
    cycle, _ = completed_cycle()
    malformed = ModelResponse.model_construct(
        content=" ", provider_name="mock", model_name="mock-model"
    )

    with pytest.raises(InvalidModelContinuationResponseError):
        build_service(FakeContinuationProvider(response=malformed)).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )


@pytest.mark.parametrize(
    "response",
    [
        ModelResponse(content="final", provider_name="gemini", model_name="mock-model"),
        ModelResponse(content="final", provider_name="mock", model_name="other-model"),
    ],
)
def test_response_identity_mismatch_is_rejected(response: ModelResponse) -> None:
    cycle, _ = completed_cycle()
    service = build_service(FakeContinuationProvider(response=response))

    expected = (
        ModelContinuationProviderMismatchError
        if response.provider_name != "mock"
        else ModelContinuationModelMismatchError
    )
    with pytest.raises(expected):
        service.continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )


class ToolCallingResponse(ModelResponse):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tool_calls: tuple[str, ...]


class FinishReasonResponse(ModelResponse):
    model_config = ConfigDict(frozen=True, extra="forbid")
    finish_reason: str


@pytest.mark.parametrize(
    "response",
    [
        ToolCallingResponse(
            content="next", provider_name="mock", model_name="mock-model", tool_calls=("call-2",)
        ),
        ToolCallingResponse(
            content="next", provider_name="mock", model_name="mock-model", tool_calls=("call-2", "call-3")
        ),
        FinishReasonResponse(
            content="next", provider_name="mock", model_name="mock-model", finish_reason="tool_calls"
        ),
    ],
)
def test_additional_or_multiple_tool_calls_are_terminally_rejected(
    response: ModelResponse,
) -> None:
    cycle, _ = completed_cycle()
    provider = FakeContinuationProvider(response=response)

    with pytest.raises(AdditionalToolCallNotSupportedError):
        build_service(provider).continue_once(
            provider_name="mock",
            model_name="mock-model",
            cycle=cycle,
            context=conversation_context(),
        )

    assert provider.calls == 1


def test_full_stage8_lifecycle_executes_tool_and_continuation_once() -> None:
    cycle, audit = completed_cycle()
    provider = FakeContinuationProvider()

    response = build_service(provider).continue_once(
        provider_name="mock",
        model_name="mock-model",
        cycle=cycle,
        context=conversation_context(),
    )

    assert response.content == "Final answer after ping."
    assert provider.calls == 1
    assert len(audit.started) == len(audit.finalized) == 1
    assert not hasattr(response, "tool_calls")


def test_constructor_only_validates_registry_without_lookup_or_invocation() -> None:
    class TrackingRegistry(ProviderRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.lookups = 0

        def get(self, name: str) -> ModelProvider:
            self.lookups += 1
            return super().get(name)

    registry = TrackingRegistry()
    provider = FakeContinuationProvider()
    registry.register(provider)

    SingleModelContinuationService(registry)

    assert registry.lookups == provider.calls == 0
    with pytest.raises(TypeError, match="provider_registry"):
        SingleModelContinuationService(object())  # type: ignore[arg-type]


def test_service_has_no_tool_execution_selection_prompt_database_network_or_fastapi_dependencies() -> None:
    source = inspect.getsource(service_module).lower()

    for forbidden in (
        "toolregistry",
        "toolexecutor",
        "singletoolexecutiongateway",
        "toolselectionservice",
        "provider_tool_call_adapter",
        ".execute(",
        "promptmanager",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "import requests",
        "repository",
        "asyncio",
        "thread",
    ):
        assert forbidden not in source
