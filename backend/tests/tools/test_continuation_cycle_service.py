"""Tests for single tool-continuation cycle orchestration."""

import inspect
from typing import Any
from uuid import uuid4

import pytest

from app.tools import (
    BaseTool,
    ExecutionContext,
    InvalidToolContinuationCycleServiceInputError,
    MockProviderContinuationAdapter,
    PingInput,
    PingOutput,
    PingTool,
    ProviderContinuationAdapterRegistry,
    ProviderContinuationPayload,
    ProviderContinuationService,
    SingleToolContinuationCycleService,
    SingleToolExecutionGateway,
    ToolCategory,
    ToolContinuationCycle,
    ToolContinuationCycleCreationError,
    ToolContinuationCycleFactory,
    ToolContinuationTranslationError,
    ToolCycleExecutionError,
    ToolError,
    ToolExecutionOutcome,
    ToolExecutionOutcomeCreationError,
    ToolExecutionOutcomeFactory,
    ToolExecutionRequest,
    ToolExecutionRequestCreationError,
    ToolExecutionRequestFactory,
    ToolExecutor,
    ToolMetadata,
    ToolRegistry,
    ToolResult,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ToolStatus,
    ValidatedToolSelection,
)
from app.tools import continuation_cycle_service as service_module
from tests.tools.audit_fakes import RecordingAuditRepository


def selection() -> ValidatedToolSelection:
    tools = ToolRegistry()
    tools.register(PingTool)
    return ToolSelectionResolver(tools).resolve(
        ToolSelectionRequest(
            call_id="Call-001",
            tool_name="ping",
            arguments={"message": "hello"},
        )
    )


def context() -> ExecutionContext:
    return ExecutionContext(trace_id=uuid4(), execution_id=uuid4())


def real_service(
    tool_class: type[BaseTool] = PingTool,
    audit: RecordingAuditRepository = None,  # type: ignore[assignment]
) -> tuple[SingleToolContinuationCycleService, RecordingAuditRepository]:
    tools = ToolRegistry()
    tools.register(tool_class)
    audit = audit or RecordingAuditRepository()
    adapters = ProviderContinuationAdapterRegistry()
    adapters.register("mock", MockProviderContinuationAdapter())
    return (
        SingleToolContinuationCycleService(
            ToolExecutionRequestFactory(),
            SingleToolExecutionGateway(tools, ToolExecutor(tools, audit)),
            ToolExecutionOutcomeFactory(),
            ProviderContinuationService(adapters),
            ToolContinuationCycleFactory(),
        ),
        audit,
    )


def test_real_ping_cycle_runs_once_and_returns_completed_cycle() -> None:
    service, audit = real_service()
    selected = selection()
    trusted_context = context()

    cycle = service.run("mock", selected, trusted_context)

    assert cycle.selection is selected
    assert cycle.execution_outcome.status is ToolStatus.SUCCESS
    assert cycle.continuation_payload.payload["output"] == {"pong": "pong"}
    assert len(audit.started) == len(audit.finalized) == 1


def test_provider_normalization_is_delegated_through_real_boundaries() -> None:
    service, _ = real_service()

    cycle = service.run("  MoCk  ", selection(), context())

    assert cycle.provider_name == "mock"


class BusinessFailurePing(BaseTool[PingInput, PingOutput]):
    metadata = ToolMetadata(
        name="ping",
        version="1.0.0",
        description="Return a controlled business failure.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("cycle_service_test",),
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
                error_code="PING_UNAVAILABLE",
                public_message="Ping is currently unavailable.",
            ),
        )


def test_business_failure_completes_cycle_and_single_audit_lifecycle() -> None:
    service, audit = real_service(BusinessFailurePing)

    cycle = service.run("mock", selection(), context())

    assert cycle.execution_outcome.status is ToolStatus.FAILURE
    assert cycle.continuation_payload.payload["status"] == "failure"
    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "failed"


class TrackingRequestFactory(ToolExecutionRequestFactory):
    def __init__(self, events: list[str], output: Any, error: Exception = None) -> None:  # type: ignore[assignment]
        self.events, self.output, self.error, self.calls = events, output, error, 0
        self.inputs: list[tuple[object, object]] = []

    def create(self, selection: Any, context: Any) -> ToolExecutionRequest:
        self.calls += 1
        self.events.append("request")
        self.inputs.append((selection, context))
        if self.error:
            raise self.error
        return self.output


class TrackingGateway(SingleToolExecutionGateway):
    def __init__(self, events: list[str], output: Any, error: Exception = None) -> None:  # type: ignore[assignment]
        self.events, self.output, self.error, self.calls = events, output, error, 0
        self.inputs: list[object] = []

    def execute(self, request: Any) -> ToolResult:
        self.calls += 1
        self.events.append("execution")
        self.inputs.append(request)
        if self.error:
            raise self.error
        return self.output


class TrackingOutcomeFactory(ToolExecutionOutcomeFactory):
    def __init__(self, events: list[str], output: Any, error: Exception = None) -> None:  # type: ignore[assignment]
        self.events, self.output, self.error, self.calls = events, output, error, 0
        self.inputs: list[tuple[object, object]] = []

    def create(self, request: Any, result: Any) -> ToolExecutionOutcome:
        self.calls += 1
        self.events.append("outcome")
        self.inputs.append((request, result))
        if self.error:
            raise self.error
        return self.output


class TrackingContinuationService(ProviderContinuationService):
    def __init__(self, events: list[str], output: Any, error: Exception = None) -> None:  # type: ignore[assignment]
        self.events, self.output, self.error, self.calls = events, output, error, 0
        self.inputs: list[tuple[object, object]] = []

    def translate(self, provider_name: Any, outcome: Any) -> ProviderContinuationPayload:
        self.calls += 1
        self.events.append("continuation")
        self.inputs.append((provider_name, outcome))
        if self.error:
            raise self.error
        return self.output


class TrackingCycleFactory(ToolContinuationCycleFactory):
    def __init__(self, events: list[str], output: Any, error: Exception = None) -> None:  # type: ignore[assignment]
        self.events, self.output, self.error, self.calls = events, output, error, 0
        self.inputs: list[tuple[object, ...]] = []

    def create(self, *artifacts: Any) -> ToolContinuationCycle:
        self.calls += 1
        self.events.append("cycle")
        self.inputs.append(artifacts)
        if self.error:
            raise self.error
        return self.output


def tracking_components(
    *, stage_error: str = ""
) -> tuple[SingleToolContinuationCycleService, dict[str, Any], list[str]]:
    events: list[str] = []
    selected = selection()
    trusted_context = context()
    request = ToolExecutionRequestFactory().create(selected, trusted_context)
    result = ToolResult[PingOutput](
        status=ToolStatus.SUCCESS, data=PingOutput(pong="pong")
    )
    outcome = ToolExecutionOutcomeFactory().create(request, result)
    payload = ProviderContinuationPayload(
        provider_name="mock",
        call_id=outcome.call_id,
        payload={"type": "tool_result"},
    )
    cycle = ToolContinuationCycleFactory().create(
        "mock", selected, request, outcome, payload
    )
    error = RuntimeError(f"{stage_error} private failure")
    components = {
        "selection": selected,
        "context": trusted_context,
        "request": request,
        "result": result,
        "outcome": outcome,
        "payload": payload,
        "cycle": cycle,
    }
    request_factory = TrackingRequestFactory(
        events, request, error if stage_error == "request" else None
    )
    gateway = TrackingGateway(
        events, result, error if stage_error == "execution" else None
    )
    outcome_factory = TrackingOutcomeFactory(
        events, outcome, error if stage_error == "outcome" else None
    )
    continuation = TrackingContinuationService(
        events, payload, error if stage_error == "continuation" else None
    )
    cycle_factory = TrackingCycleFactory(
        events, cycle, error if stage_error == "cycle" else None
    )
    components.update(
        request_factory=request_factory,
        gateway=gateway,
        outcome_factory=outcome_factory,
        continuation=continuation,
        cycle_factory=cycle_factory,
        error=error,
    )
    service = SingleToolContinuationCycleService(
        request_factory, gateway, outcome_factory, continuation, cycle_factory
    )
    return service, components, events


def test_exact_order_once_propagation_and_original_cycle_return() -> None:
    service, parts, events = tracking_components()

    cycle = service.run(" MOCK ", parts["selection"], parts["context"])

    assert events == ["request", "execution", "outcome", "continuation", "cycle"]
    assert cycle is parts["cycle"]
    assert parts["request_factory"].calls == 1
    assert parts["gateway"].calls == 1
    assert parts["outcome_factory"].calls == 1
    assert parts["continuation"].calls == 1
    assert parts["cycle_factory"].calls == 1
    assert parts["request_factory"].inputs == [
        (parts["selection"], parts["context"])
    ]
    assert parts["gateway"].inputs == [parts["request"]]
    assert parts["outcome_factory"].inputs == [
        (parts["request"], parts["result"])
    ]
    assert parts["continuation"].inputs == [(" MOCK ", parts["outcome"])]
    assert parts["cycle_factory"].inputs == [
        (
            " MOCK ",
            parts["selection"],
            parts["request"],
            parts["outcome"],
            parts["payload"],
        )
    ]


@pytest.mark.parametrize("invalid", [{}, object(), ToolSelectionRequest(call_id="x", tool_name="ping", arguments={"message": "x"}), [selection()], (selection(),)])
def test_invalid_raw_or_batch_selection_is_rejected_before_lifecycle(invalid: object) -> None:
    service, _, events = tracking_components()

    with pytest.raises(InvalidToolContinuationCycleServiceInputError):
        service.run("mock", invalid, context())  # type: ignore[arg-type]

    assert events == []


@pytest.mark.parametrize("invalid", [{}, object(), [context()], (context(),)])
def test_invalid_context_is_rejected_before_lifecycle(invalid: object) -> None:
    service, parts, events = tracking_components()

    with pytest.raises(InvalidToolContinuationCycleServiceInputError):
        service.run("mock", parts["selection"], invalid)  # type: ignore[arg-type]

    assert events == []


@pytest.mark.parametrize("invalid", ["", " ", None, 42, {}])
def test_invalid_provider_is_rejected_before_lifecycle(invalid: object) -> None:
    service, parts, events = tracking_components()

    with pytest.raises(InvalidToolContinuationCycleServiceInputError):
        service.run(invalid, parts["selection"], parts["context"])  # type: ignore[arg-type]

    assert events == []


@pytest.mark.parametrize(
    ("stage", "expected_error", "expected_events"),
    [
        ("request", ToolExecutionRequestCreationError, ["request"]),
        ("execution", ToolCycleExecutionError, ["request", "execution"]),
        (
            "outcome",
            ToolExecutionOutcomeCreationError,
            ["request", "execution", "outcome"],
        ),
        (
            "continuation",
            ToolContinuationTranslationError,
            ["request", "execution", "outcome", "continuation"],
        ),
        (
            "cycle",
            ToolContinuationCycleCreationError,
            ["request", "execution", "outcome", "continuation", "cycle"],
        ),
    ],
)
def test_stage_failure_is_wrapped_with_cause_and_stops_later_stages(
    stage: str, expected_error: type[Exception], expected_events: list[str]
) -> None:
    service, parts, events = tracking_components(stage_error=stage)

    with pytest.raises(expected_error) as captured:
        service.run("mock", parts["selection"], parts["context"])

    assert captured.value.__cause__ is parts["error"]
    assert "private failure" not in str(captured.value)
    assert events == expected_events


class ExplodingPing(BaseTool[PingInput, PingOutput]):
    metadata = ToolMetadata(
        name="ping",
        version="1.0.0",
        description="Raise an unexpected test-only execution error.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("cycle_service_test",),
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
        raise RuntimeError("private tool exception")


def test_unexpected_tool_exception_is_execution_error_and_audited_once() -> None:
    service, audit = real_service(ExplodingPing)

    with pytest.raises(ToolCycleExecutionError) as captured:
        service.run("mock", selection(), context())

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "error"


class ConstructionExplodingPing(BaseTool[PingInput, PingOutput]):
    metadata = ToolMetadata(
        name="ping",
        version="1.0.0",
        description="Raise during test-only tool construction.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("cycle_service_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
        is_enabled=True,
    )
    input_schema = PingInput
    output_schema = PingOutput

    def __init__(self) -> None:
        raise RuntimeError("private construction failure")

    def execute(
        self, context: ExecutionContext, input_model: PingInput
    ) -> ToolResult[PingOutput]:
        raise AssertionError("construction failure must prevent execution")


def test_tool_construction_failure_stops_as_execution_error_and_is_audited() -> None:
    service, audit = real_service(ConstructionExplodingPing)

    with pytest.raises(ToolCycleExecutionError) as captured:
        service.run("mock", selection(), context())

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "error"


class FailingAuditRepository(RecordingAuditRepository):
    def create_running(self, **values: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("private audit failure")


def test_audit_failure_stops_execution_without_partial_cycle() -> None:
    audit = FailingAuditRepository()
    service, _ = real_service(PingTool, audit)

    with pytest.raises(ToolCycleExecutionError) as captured:
        service.run("mock", selection(), context())

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert audit.started == audit.finalized == []


def test_real_continuation_lookup_failure_is_wrapped_at_continuation_stage() -> None:
    service, parts, events = tracking_components()
    missing = ProviderContinuationService(ProviderContinuationAdapterRegistry())
    service = SingleToolContinuationCycleService(
        parts["request_factory"],
        parts["gateway"],
        parts["outcome_factory"],
        missing,
        parts["cycle_factory"],
    )

    with pytest.raises(ToolContinuationTranslationError) as captured:
        service.run("missing", parts["selection"], parts["context"])

    assert events == ["request", "execution", "outcome"]
    assert parts["cycle_factory"].calls == 0
    assert captured.value.__cause__ is not None


@pytest.mark.parametrize(
    ("index", "name", "expected"),
    [
        (0, "execution_request_factory", ToolExecutionRequestFactory),
        (1, "execution_gateway", SingleToolExecutionGateway),
        (2, "execution_outcome_factory", ToolExecutionOutcomeFactory),
        (3, "continuation_service", ProviderContinuationService),
        (4, "cycle_factory", ToolContinuationCycleFactory),
    ],
)
def test_constructor_validates_each_dependency_without_running_lifecycle(
    index: int, name: str, expected: type
) -> None:
    service, parts, events = tracking_components()
    dependencies = [
        parts["request_factory"],
        parts["gateway"],
        parts["outcome_factory"],
        parts["continuation"],
        parts["cycle_factory"],
    ]
    dependencies[index] = object()

    with pytest.raises(TypeError, match=name):
        SingleToolContinuationCycleService(*dependencies)  # type: ignore[arg-type]

    assert events == []
    assert isinstance(expected, type)


def test_service_has_no_model_provider_prompt_selection_translation_or_io_dependencies() -> None:
    source = inspect.getsource(service_module).lower()

    for forbidden in (
        "provider_tool_call_adapter",
        "toolselectionresolver",
        "toolselectionservice",
        "modelprovider",
        "app.providers",
        "prompt",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "requests",
        "asyncio",
        "thread",
        "repository",
    ):
        assert forbidden not in source
