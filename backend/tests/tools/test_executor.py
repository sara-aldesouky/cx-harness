"""Pure unit tests for minimal tool execution orchestration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.tools import (
    BaseTool,
    ExecutionContext,
    ToolCategory,
    ToolExecutionContractError,
    ToolMetadata,
    ToolNotFoundError,
    ToolRegistry,
    ToolResult,
    ToolStatus,
)
from app.tools.executor import ToolExecutor
from tests.tools.audit_fakes import RecordingAuditRepository


class DemoInput(BaseModel):
    value: str


class OtherInput(BaseModel):
    value: str


class DemoOutput(BaseModel):
    echoed: str


def tool_metadata(name: str) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        version="1.0.0",
        description="A unit-test-only tool.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("executor_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
    )


def execution_context() -> ExecutionContext:
    return ExecutionContext(trace_id=uuid4(), execution_id=uuid4())


class DemoTool(BaseTool[DemoInput, DemoOutput]):
    metadata = tool_metadata("demo")
    input_schema = DemoInput
    output_schema = DemoOutput
    received_context: ExecutionContext | None = None
    received_input: DemoInput | None = None

    def execute(
        self,
        context: ExecutionContext,
        input_model: DemoInput,
    ) -> ToolResult[DemoOutput]:
        type(self).received_context = context
        type(self).received_input = input_model
        return ToolResult[DemoOutput](
            status=ToolStatus.SUCCESS,
            data=DemoOutput(echoed=input_model.value),
        )


def executor_for(tool_class: type[BaseTool]) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(tool_class)
    return ToolExecutor(registry, RecordingAuditRepository())


def test_successful_execution_returns_standard_result() -> None:
    executor = executor_for(DemoTool)

    result = executor.execute(
        "demo", "1.0.0", execution_context(), DemoInput(value="hello")
    )

    assert isinstance(result, ToolResult)
    assert result.status is ToolStatus.SUCCESS
    assert result.data == DemoOutput(echoed="hello")


def test_registry_is_consulted_for_resolution() -> None:
    class RecordingRegistry(ToolRegistry):
        requested: tuple[str, str] | None = None

        def get(self, name: str, version: str):
            self.requested = (name, version)
            return super().get(name, version)

    registry = RecordingRegistry()
    registry.register(DemoTool)
    executor = ToolExecutor(registry, RecordingAuditRepository())

    executor.execute(
        "demo", "1.0.0", execution_context(), DemoInput(value="hello")
    )

    assert registry.requested == ("demo", "1.0.0")


def test_unknown_tool_preserves_registry_lookup_error() -> None:
    executor = ToolExecutor(ToolRegistry(), RecordingAuditRepository())

    with pytest.raises(ToolNotFoundError, match="is not registered"):
        executor.execute(
            "missing", "1.0.0", execution_context(), DemoInput(value="hello")
        )


def test_invalid_input_model_type_is_rejected_before_invocation() -> None:
    executor = executor_for(DemoTool)
    DemoTool.received_input = None

    with pytest.raises(ToolExecutionContractError, match="DemoInput"):
        executor.execute(
            "demo", "1.0.0", execution_context(), OtherInput(value="hello")
        )

    assert DemoTool.received_input is None


def test_invalid_context_type_is_rejected() -> None:
    executor = executor_for(DemoTool)

    with pytest.raises(ToolExecutionContractError, match="ExecutionContext"):
        executor.execute(
            "demo",
            "1.0.0",
            object(),  # type: ignore[arg-type]
            DemoInput(value="hello"),
        )


def test_execution_context_and_validated_input_reach_tool_unchanged() -> None:
    executor = executor_for(DemoTool)
    context = execution_context()
    input_model = DemoInput(value="trusted")

    executor.execute("demo", "1.0.0", context, input_model)

    assert DemoTool.received_context is context
    assert DemoTool.received_input is input_model


def test_invalid_execution_return_type_is_rejected() -> None:
    class InvalidReturnTool(BaseTool[DemoInput, DemoOutput]):
        metadata = tool_metadata("invalid_return")
        input_schema = DemoInput
        output_schema = DemoOutput

        def execute(
            self,
            context: ExecutionContext,
            input_model: DemoInput,
        ) -> ToolResult[DemoOutput]:
            return {"status": "success"}  # type: ignore[return-value]

    executor = executor_for(InvalidReturnTool)

    with pytest.raises(ToolExecutionContractError, match="ToolResult"):
        executor.execute(
            "invalid_return",
            "1.0.0",
            execution_context(),
            DemoInput(value="hello"),
        )


def test_success_result_with_wrong_output_model_is_rejected() -> None:
    class WrongOutputTool(BaseTool[DemoInput, DemoOutput]):
        metadata = tool_metadata("wrong_output")
        input_schema = DemoInput
        output_schema = DemoOutput

        def execute(
            self,
            context: ExecutionContext,
            input_model: DemoInput,
        ) -> ToolResult[DemoOutput]:
            return ToolResult[OtherInput](
                status=ToolStatus.SUCCESS,
                data=OtherInput(value="wrong"),
            )  # type: ignore[return-value]

    executor = executor_for(WrongOutputTool)

    with pytest.raises(ToolExecutionContractError, match="DemoOutput"):
        executor.execute(
            "wrong_output",
            "1.0.0",
            execution_context(),
            DemoInput(value="hello"),
        )


def test_executor_only_invokes_the_registered_tool() -> None:
    events = {"registered": 0, "unregistered": 0}

    class RegisteredTool(BaseTool[DemoInput, DemoOutput]):
        metadata = tool_metadata("registered")
        input_schema = DemoInput
        output_schema = DemoOutput

        def execute(
            self,
            context: ExecutionContext,
            input_model: DemoInput,
        ) -> ToolResult[DemoOutput]:
            events["registered"] += 1
            return ToolResult[DemoOutput](
                status=ToolStatus.SUCCESS,
                data=DemoOutput(echoed=input_model.value),
            )

    class UnregisteredTool(BaseTool[DemoInput, DemoOutput]):
        metadata = tool_metadata("unregistered")
        input_schema = DemoInput
        output_schema = DemoOutput

        def execute(
            self,
            context: ExecutionContext,
            input_model: DemoInput,
        ) -> ToolResult[DemoOutput]:
            events["unregistered"] += 1
            return ToolResult[DemoOutput](
                status=ToolStatus.SUCCESS,
                data=DemoOutput(echoed=input_model.value),
            )

    executor = executor_for(RegisteredTool)
    executor.execute(
        "registered", "1.0.0", execution_context(), DemoInput(value="hello")
    )

    assert events == {"registered": 1, "unregistered": 0}
