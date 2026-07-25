"""Tests for the single raw provider tool-call application service."""

import inspect
from typing import Any
from uuid import uuid4

import pytest

from app.tools import (
    BaseTool,
    ExecutionContext,
    InvalidProviderToolCallCycleInputError,
    InvalidProviderToolCallCycleResultError,
    InvalidProviderToolCallSelectionCountError,
    MockProviderContinuationAdapter,
    MockProviderToolCallAdapter,
    PingInput,
    PingOutput,
    PingTool,
    ProviderContinuationAdapterRegistry,
    ProviderContinuationPayload,
    ProviderToolCallAdapterRegistry,
    ProviderToolCallCycleExecutionError,
    ProviderToolCallSelectionError,
    SingleProviderToolCallCycleService,
    SingleToolContinuationCycleService,
    ToolCategory,
    ToolContinuationCycle,
    ToolContinuationRuntime,
    ToolError,
    ToolExecutionOutcome,
    ToolExecutionRequest,
    ToolMetadata,
    ToolRegistry,
    ToolResult,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ToolSelectionService,
    ToolStatus,
    ValidatedToolSelection,
    build_tool_continuation_runtime,
)
from app.tools import provider_cycle_service as service_module
from tests.tools.audit_fakes import RecordingAuditRepository


def provider_payload(
    *,
    call_id: object = "call-001",
    name: object = "ping",
    arguments: object = None,
) -> dict[str, object]:
    return {
        "tool_calls": [
            {
                "id": call_id,
                "name": name,
                "version": "1.0.0",
                "arguments": (
                    {"message": "hello"} if arguments is None else arguments
                ),
            }
        ]
    }


def trusted_context() -> ExecutionContext:
    return ExecutionContext(trace_id=uuid4(), execution_id=uuid4())


def build_real_service(
    *,
    tool_class: type[BaseTool] = PingTool,
    register_provider_adapter: bool = True,
) -> tuple[SingleProviderToolCallCycleService, RecordingAuditRepository]:
    tools = ToolRegistry()
    tools.register(tool_class)
    provider_adapters = ProviderToolCallAdapterRegistry()
    if register_provider_adapter:
        provider_adapters.register("mock", MockProviderToolCallAdapter())
    selection_service = ToolSelectionService(
        provider_adapters, ToolSelectionResolver(tools)
    )
    continuations = ProviderContinuationAdapterRegistry()
    continuations.register("mock", MockProviderContinuationAdapter())
    audit = RecordingAuditRepository()
    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
    )
    return SingleProviderToolCallCycleService(selection_service, runtime), audit


def test_real_mock_provider_ping_cycle_runs_end_to_end_once() -> None:
    service, audit = build_real_service()
    raw = provider_payload()
    context = trusted_context()

    cycle = service.run("mock", raw, context)

    assert isinstance(cycle, ToolContinuationCycle)
    assert cycle.provider_name == "mock"
    assert cycle.selection.call_id == "call-001"
    assert cycle.execution_request.context == context
    assert cycle.continuation_payload.payload["output"] == {"pong": "pong"}
    assert len(audit.started) == len(audit.finalized) == 1


def test_provider_name_normalization_flows_through_selection_and_runtime() -> None:
    service, _ = build_real_service()

    cycle = service.run("  MoCk  ", provider_payload(), trusted_context())

    assert cycle.provider_name == "mock"


class BusinessFailurePing(BaseTool[PingInput, PingOutput]):
    metadata = ToolMetadata(
        name="ping",
        version="1.0.0",
        description="Return a test-only business failure.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("provider_cycle_service_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
        is_enabled=True,
    )
    input_schema = PingInput
    output_schema = PingOutput

    def execute(
        self, context: ExecutionContext, input_model: PingInput
    ) -> ToolResult[PingOutput]:
        return ToolResult[PingOutput](
            status=ToolStatus.FAILURE,
            error=ToolError(
                error_code="PING_FAILED",
                public_message="Ping could not be completed.",
            ),
        )


class DisabledPing(BaseTool[PingInput, PingOutput]):
    metadata = ToolMetadata(
        name="ping",
        version="1.0.0",
        description="Disabled test-only declaration.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("provider_cycle_service_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
        is_enabled=False,
    )
    input_schema = PingInput
    output_schema = PingOutput

    def execute(
        self, context: ExecutionContext, input_model: PingInput
    ) -> ToolResult[PingOutput]:
        raise AssertionError("disabled tool must never execute")


def test_business_failure_returns_completed_cycle_without_duplicate_audit() -> None:
    service, audit = build_real_service(tool_class=BusinessFailurePing)

    cycle = service.run("mock", provider_payload(), trusted_context())

    assert cycle.execution_outcome.status is ToolStatus.FAILURE
    assert cycle.continuation_payload.payload["status"] == "failure"
    assert len(audit.started) == len(audit.finalized) == 1


def test_disabled_tool_selection_stops_before_execution_and_audit() -> None:
    service, audit = build_real_service(tool_class=DisabledPing)

    with pytest.raises(ProviderToolCallSelectionError):
        service.run("mock", provider_payload(), trusted_context())

    assert audit.started == audit.finalized == []


def sample_selection() -> ValidatedToolSelection:
    tools = ToolRegistry()
    tools.register(PingTool)
    return ToolSelectionResolver(tools).resolve(
        ToolSelectionRequest(
            call_id="call-001",
            tool_name="ping",
            arguments={"message": "hello"},
        )
    )


class TrackingSelectionService(ToolSelectionService):
    def __init__(self, events: list[str], output: Any, error: Exception = None) -> None:  # type: ignore[assignment]
        self.events, self.output, self.error, self.calls = events, output, error, 0
        self.inputs: list[tuple[object, object]] = []

    def select(self, provider_name: str, provider_output: object):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.events.append("selection")
        self.inputs.append((provider_name, provider_output))
        if self.error:
            raise self.error
        return self.output


class TrackingCycleService(SingleToolContinuationCycleService):
    def __init__(self, events: list[str], output: Any, error: Exception = None) -> None:  # type: ignore[assignment]
        self.events, self.output, self.error, self.calls = events, output, error, 0
        self.inputs: list[tuple[object, object, object]] = []

    def run(self, provider_name: str, selection: Any, context: Any):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.events.append("runtime")
        self.inputs.append((provider_name, selection, context))
        if self.error:
            raise self.error
        return self.output


_DEFAULT = object()


def tracking_service(
    *,
    selection_output: Any = _DEFAULT,
    selection_error: Exception = None,
    runtime_output: Any = _DEFAULT,
    runtime_error: Exception = None,
) -> tuple[SingleProviderToolCallCycleService, dict[str, Any], list[str]]:
    real_service, _ = build_real_service()
    selected = sample_selection()
    context = trusted_context()
    cycle = real_service.run("mock", provider_payload(), context)
    events: list[str] = []
    selector = TrackingSelectionService(
        events,
        (selected,) if selection_output is _DEFAULT else selection_output,
        selection_error,
    )
    runner = TrackingCycleService(
        events, cycle if runtime_output is _DEFAULT else runtime_output, runtime_error
    )
    runtime = ToolContinuationRuntime(cycle_service=runner)
    return (
        SingleProviderToolCallCycleService(selector, runtime),
        {
            "selector": selector,
            "runner": runner,
            "selection": selected,
            "context": context,
            "cycle": cycle,
        },
        events,
    )


def test_raw_payload_selection_context_provider_and_cycle_instances_propagate() -> None:
    service, parts, events = tracking_service()
    raw = {"private_provider_shape": {"call": "opaque"}}

    result = service.run(" MOCK ", raw, parts["context"])

    assert events == ["selection", "runtime"]
    assert parts["selector"].calls == parts["runner"].calls == 1
    assert parts["selector"].inputs == [(" MOCK ", raw)]
    assert parts["selector"].inputs[0][1] is raw
    assert parts["runner"].inputs == [
        (" MOCK ", parts["selection"], parts["context"])
    ]
    assert result is parts["cycle"]


@pytest.mark.parametrize("provider", ["", " ", None, 42])
def test_invalid_provider_is_rejected_before_selection(provider: object) -> None:
    service, parts, events = tracking_service()

    with pytest.raises(InvalidProviderToolCallCycleInputError):
        service.run(provider, provider_payload(), parts["context"])  # type: ignore[arg-type]

    assert events == []


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        (),
        [provider_payload()],
        (provider_payload(),),
        sample_selection(),
        ToolSelectionRequest(
            call_id="call", tool_name="ping", arguments={"message": "hello"}
        ),
    ],
)
def test_non_raw_and_batch_payloads_are_rejected(invalid: object) -> None:
    service, parts, events = tracking_service()

    with pytest.raises(InvalidProviderToolCallCycleInputError):
        service.run("mock", invalid, parts["context"])

    assert events == []


def test_invalid_context_is_rejected_before_selection() -> None:
    service, _, events = tracking_service()

    with pytest.raises(InvalidProviderToolCallCycleInputError):
        service.run("mock", provider_payload(), object())  # type: ignore[arg-type]

    assert events == []


@pytest.mark.parametrize("selections", [(), (sample_selection(), sample_selection()), [], None])
def test_zero_multiple_or_invalid_selection_collection_is_rejected(
    selections: object,
) -> None:
    service, parts, events = tracking_service(selection_output=selections)

    with pytest.raises(InvalidProviderToolCallSelectionCountError):
        service.run("mock", provider_payload(), parts["context"])

    assert events == ["selection"]
    assert parts["runner"].calls == 0


def test_single_invalid_selection_artifact_stops_before_runtime() -> None:
    service, parts, events = tracking_service(selection_output=({},))

    with pytest.raises(ProviderToolCallSelectionError):
        service.run("mock", provider_payload(), parts["context"])

    assert events == ["selection"]
    assert parts["runner"].calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_calls": "malformed"},
        provider_payload(call_id=" "),
        provider_payload(name="missing"),
        provider_payload(arguments={"message": " "}),
    ],
)
def test_real_selection_failures_prevent_execution_and_audit(payload: object) -> None:
    service, audit = build_real_service()

    with pytest.raises(ProviderToolCallSelectionError) as captured:
        service.run("mock", payload, trusted_context())

    assert captured.value.__cause__ is not None
    assert audit.started == audit.finalized == []


def test_unknown_provider_adapter_prevents_runtime_and_audit() -> None:
    service, audit = build_real_service(register_provider_adapter=False)

    with pytest.raises(ProviderToolCallSelectionError):
        service.run("unknown", provider_payload(), trusted_context())

    assert audit.started == audit.finalized == []


def test_selection_failure_is_safe_preserves_cause_and_does_not_retry() -> None:
    original = RuntimeError("private provider response secret")
    service, parts, events = tracking_service(selection_error=original)

    with pytest.raises(ProviderToolCallSelectionError) as captured:
        service.run("mock", {"raw": "secret"}, parts["context"])

    assert captured.value.__cause__ is original
    assert "secret" not in str(captured.value)
    assert parts["selector"].calls == 1
    assert parts["runner"].calls == 0
    assert events == ["selection"]


def test_runtime_failure_is_safe_preserves_cause_and_does_not_retry() -> None:
    original = RuntimeError("private runtime secret")
    service, parts, events = tracking_service(runtime_error=original)

    with pytest.raises(ProviderToolCallCycleExecutionError) as captured:
        service.run("mock", provider_payload(), parts["context"])

    assert captured.value.__cause__ is original
    assert "secret" not in str(captured.value)
    assert parts["selector"].calls == parts["runner"].calls == 1
    assert events == ["selection", "runtime"]


@pytest.mark.parametrize("invalid", [None, {}, object()])
def test_invalid_runtime_result_is_rejected(invalid: object) -> None:
    service, parts, events = tracking_service(runtime_output=invalid)

    with pytest.raises(InvalidProviderToolCallCycleResultError):
        service.run("mock", provider_payload(), parts["context"])

    assert events == ["selection", "runtime"]


def test_provider_mismatched_cycle_is_rejected_without_reconstruction() -> None:
    service, parts, events = tracking_service()
    wrong = parts["cycle"].model_copy(update={"provider_name": "gemini"})
    parts["runner"].output = wrong

    with pytest.raises(InvalidProviderToolCallCycleResultError):
        service.run("mock", provider_payload(), parts["context"])

    assert wrong.provider_name == "gemini"
    assert events == ["selection", "runtime"]


def test_constructor_validates_dependencies_without_lifecycle_activity() -> None:
    service, parts, events = tracking_service()

    with pytest.raises(TypeError, match="selection_service"):
        SingleProviderToolCallCycleService(object(), ToolContinuationRuntime(parts["runner"]))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="runtime"):
        SingleProviderToolCallCycleService(parts["selector"], object())  # type: ignore[arg-type]

    assert events == []


def test_service_has_no_model_prompt_database_network_fastapi_or_composition_dependencies() -> None:
    source = inspect.getsource(service_module).lower()

    for forbidden in (
        "modelprovider",
        "app.providers",
        "prompt",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "requests",
        "repository",
        "build_tool_continuation_runtime",
        ".register(",
        "asyncio",
        "thread",
    ):
        assert forbidden not in source
