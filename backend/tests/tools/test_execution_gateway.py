"""Focused tests for the single tool execution gateway."""

import inspect
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.tools import (
    BaseTool,
    DisabledToolExecutionError,
    ExecutionContext,
    InvalidToolExecutionGatewayRequestError,
    PingInput,
    PingOutput,
    PingTool,
    SingleToolExecutionGateway,
    ToolCategory,
    ToolError,
    ToolExecutionRequest,
    ToolExecutionRequestFactory,
    ToolExecutor,
    ToolMetadata,
    ToolNotFoundError,
    ToolRegistry,
    ToolResult,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ToolStatus,
    ToolInputRehydrationError,
    ValidatedToolSelection,
)
from app.tools import execution_gateway as gateway_module
from tests.tools.audit_fakes import RecordingAuditRepository


def context() -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        conversation_id=uuid4(),
        customer_id=uuid4(),
    )


def request_for(
    registry: ToolRegistry,
    *,
    name: str = "ping",
    version: str = "1.0.0",
    arguments: dict[str, object] = None,  # type: ignore[assignment]
    execution_context: ExecutionContext = None,  # type: ignore[assignment]
) -> ToolExecutionRequest:
    selection = ToolSelectionResolver(registry).resolve(
        ToolSelectionRequest(
            call_id="call-001",
            tool_name=name,
            tool_version=version,
            arguments=arguments or {"message": "hello"},
        )
    )
    return ToolExecutionRequestFactory().create(
        selection, execution_context or context()
    )


def gateway_for(
    registry: ToolRegistry,
    audit: RecordingAuditRepository = None,  # type: ignore[assignment]
) -> tuple[SingleToolExecutionGateway, RecordingAuditRepository]:
    recording_audit = audit or RecordingAuditRepository()
    executor = ToolExecutor(registry, recording_audit)
    return SingleToolExecutionGateway(registry, executor), recording_audit


def metadata(name: str, *, enabled: bool = True) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        version="1.0.0",
        description=f"Gateway test tool {name}.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("gateway_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
        is_enabled=enabled,
    )


def test_real_ping_executes_once_and_preserves_existing_result_contract() -> None:
    registry = ToolRegistry()
    registry.register(PingTool)
    gateway, audit = gateway_for(registry)

    result = gateway.execute(request_for(registry))

    assert isinstance(result, ToolResult)
    assert result.status is ToolStatus.SUCCESS
    assert result.data.model_dump() == {"pong": "pong"}
    assert len(audit.started) == len(audit.finalized) == 1


def test_exact_identity_context_and_normalized_arguments_reach_executor() -> None:
    class RecordingExecutor(ToolExecutor):
        def __init__(self, registry: ToolRegistry) -> None:
            super().__init__(registry, RecordingAuditRepository())
            self.calls: list[tuple] = []

        def execute(self, name, version, execution_context, input_model):
            self.calls.append((name, version, execution_context, input_model))
            return super().execute(name, version, execution_context, input_model)

    registry = ToolRegistry()
    registry.register(PingTool)
    executor = RecordingExecutor(registry)
    gateway = SingleToolExecutionGateway(registry, executor)
    execution_context = context()
    request = request_for(
        registry,
        arguments={"message": " normalized "},
        execution_context=execution_context,
    )

    gateway.execute(request)

    assert len(executor.calls) == 1
    name, version, received_context, received_input = executor.calls[0]
    assert (name, version) == ("ping", "1.0.0")
    assert received_context is request.context
    assert received_input == PingInput(message="normalized")
    assert request.call_id == "call-001"


def test_registry_lookup_is_exact_with_no_name_or_version_fallback() -> None:
    class RecordingRegistry(ToolRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.lookups: list[tuple[str, str]] = []

        def get(self, name: str, version: str = None):  # type: ignore[override,assignment]
            self.lookups.append((name, version))
            return super().get(name, version)

    registry = RecordingRegistry()
    registry.register(PingTool)
    request = request_for(registry)
    registry.lookups.clear()
    gateway, _ = gateway_for(registry)

    gateway.execute(request)

    assert registry.lookups == [("ping", "1.0.0"), ("ping", "1.0.0")]
    assert all(version is not None for _, version in registry.lookups)


def test_unknown_exact_version_is_rejected_without_fallback_or_audit() -> None:
    registry = ToolRegistry()
    registry.register(PingTool)
    request = ToolExecutionRequestFactory().create(
        ValidatedToolSelection(
            call_id="call-001",
            tool_name="ping",
            tool_version="2.0.0",
            arguments={"message": "hello"},
        ),
        context(),
    )
    gateway, audit = gateway_for(registry)

    with pytest.raises(ToolNotFoundError, match="2.0.0"):
        gateway.execute(request)

    assert audit.started == []


def test_tool_removed_after_selection_is_rejected() -> None:
    selection_registry = ToolRegistry()
    selection_registry.register(PingTool)
    request = request_for(selection_registry)
    execution_registry = ToolRegistry()
    gateway, audit = gateway_for(execution_registry)

    with pytest.raises(ToolNotFoundError):
        gateway.execute(request)

    assert audit.started == []


def test_tool_disabled_after_selection_is_rejected_before_executor() -> None:
    class DisableAfterSelectionTool(BaseTool[PingInput, BaseModel]):
        metadata = metadata("disable_after_selection")
        input_schema = PingInput
        output_schema = BaseModel

        def execute(self, execution_context, input_model):
            raise AssertionError("disabled tool must not execute")

    registry = ToolRegistry()
    registry.register(DisableAfterSelectionTool)
    request = request_for(registry, name="disable_after_selection")
    DisableAfterSelectionTool.metadata = DisableAfterSelectionTool.metadata.model_copy(
        update={"is_enabled": False}
    )
    gateway, audit = gateway_for(registry)

    with pytest.raises(DisabledToolExecutionError, match="is disabled"):
        gateway.execute(request)

    assert audit.started == []


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"provider_output": "raw"},
        ToolSelectionRequest(
            call_id="call-001",
            tool_name="ping",
            arguments={"message": "hello"},
        ),
        ValidatedToolSelection(
            call_id="call-001",
            tool_name="ping",
            tool_version="1.0.0",
            arguments={"message": "hello"},
        ),
        (),
    ],
)
def test_gateway_accepts_only_one_execution_request(invalid: object) -> None:
    registry = ToolRegistry()
    registry.register(PingTool)
    gateway, audit = gateway_for(registry)

    with pytest.raises(InvalidToolExecutionGatewayRequestError):
        gateway.execute(invalid)  # type: ignore[arg-type]

    assert audit.started == []


def test_input_rehydration_failure_is_safe_and_precedes_audit() -> None:
    registry = ToolRegistry()
    registry.register(PingTool)
    request = ToolExecutionRequestFactory().create(
        ValidatedToolSelection(
            call_id="call-sensitive",
            tool_name="ping",
            tool_version="1.0.0",
            arguments={"private": "do-not-expose"},
        ),
        context(),
    )
    gateway, audit = gateway_for(registry)

    with pytest.raises(ToolInputRehydrationError) as captured:
        gateway.execute(request)

    assert "do-not-expose" not in str(captured.value)
    assert audit.started == []


def test_tool_construction_failure_is_audited_and_propagated() -> None:
    class DependencyTool(BaseTool[PingInput, BaseModel]):
        metadata = metadata("dependency_tool")
        input_schema = PingInput
        output_schema = BaseModel

        def __init__(self, required_dependency: object) -> None:
            self.required_dependency = required_dependency

        def execute(self, execution_context, input_model):
            raise AssertionError("construction must fail first")

    registry = ToolRegistry()
    registry.register(DependencyTool)
    gateway, audit = gateway_for(registry)

    with pytest.raises(TypeError, match="required_dependency"):
        gateway.execute(request_for(registry, name="dependency_tool"))

    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "error"
    assert audit.finalized[0]["exception_type"] == "TypeError"


def test_tool_domain_failure_is_returned_and_audited_once() -> None:
    class BusinessFailureTool(BaseTool[PingInput, BaseModel]):
        metadata = metadata("business_failure")
        input_schema = PingInput
        output_schema = BaseModel

        def execute(self, execution_context, input_model):
            return ToolResult[BaseModel](
                status=ToolStatus.FAILURE,
                error=ToolError(
                    error_code="expected_failure",
                    public_message="The operation could not be completed.",
                ),
            )

    registry = ToolRegistry()
    registry.register(BusinessFailureTool)
    gateway, audit = gateway_for(registry)

    result = gateway.execute(request_for(registry, name="business_failure"))

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "expected_failure"
    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "failed"


def test_timeout_error_uses_existing_executor_failure_behavior() -> None:
    class TimeoutTool(BaseTool[PingInput, BaseModel]):
        metadata = metadata("timeout_tool")
        input_schema = PingInput
        output_schema = BaseModel

        def execute(self, execution_context, input_model):
            raise TimeoutError("unit-test timeout")

    registry = ToolRegistry()
    registry.register(TimeoutTool)
    gateway, audit = gateway_for(registry)

    with pytest.raises(TimeoutError, match="unit-test timeout"):
        gateway.execute(request_for(registry, name="timeout_tool"))

    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "error"
    assert audit.finalized[0]["exception_type"] == "TimeoutError"


def test_executor_failure_is_not_swallowed_or_retried() -> None:
    class ExplodingExecutor(ToolExecutor):
        def __init__(self, registry: ToolRegistry) -> None:
            super().__init__(registry, RecordingAuditRepository())
            self.calls = 0

        def execute(self, name, version, execution_context, input_model):
            self.calls += 1
            raise RuntimeError("executor unavailable")

    registry = ToolRegistry()
    registry.register(PingTool)
    executor = ExplodingExecutor(registry)
    gateway = SingleToolExecutionGateway(registry, executor)

    with pytest.raises(RuntimeError, match="executor unavailable"):
        gateway.execute(request_for(registry))

    assert executor.calls == 1


def test_tool_is_instantiated_and_executed_exactly_once() -> None:
    events = {"instances": 0, "executions": 0}

    class CountingTool(BaseTool[PingInput, PingOutput]):
        metadata = metadata("counting_tool")
        input_schema = PingInput
        output_schema = PingOutput

        def __init__(self) -> None:
            events["instances"] += 1

        def execute(self, execution_context, input_model):
            events["executions"] += 1
            return ToolResult[PingOutput](
                status=ToolStatus.SUCCESS,
                data=PingOutput(pong="pong"),
            )

    registry = ToolRegistry()
    registry.register(CountingTool)
    gateway, audit = gateway_for(registry)

    gateway.execute(request_for(registry, name="counting_tool"))

    assert events == {"instances": 1, "executions": 1}
    assert len(audit.started) == len(audit.finalized) == 1


def test_constructor_validates_dependencies() -> None:
    registry = ToolRegistry()
    executor = ToolExecutor(registry, RecordingAuditRepository())

    with pytest.raises(TypeError, match="registry"):
        SingleToolExecutionGateway(object(), executor)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="executor"):
        SingleToolExecutionGateway(registry, object())  # type: ignore[arg-type]


def test_gateway_has_no_provider_fastapi_continuation_or_batch_dependencies() -> None:
    source = inspect.getsource(gateway_module).lower()

    for forbidden in (
        "app.providers",
        "fastapi",
        "providercontinuation",
        "modelprovider",
        "batch",
        "prompt",
    ):
        assert forbidden not in source
