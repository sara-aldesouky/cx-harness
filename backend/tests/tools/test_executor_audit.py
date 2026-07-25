"""Unit tests for executor-owned ToolCall audit orchestration."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.tools import (
    BaseTool,
    ExecutionContext,
    ToolCategory,
    ToolError,
    ToolExecutor,
    ToolMetadata,
    ToolRegistry,
    ToolResult,
    ToolStatus,
)
from tests.tools.audit_fakes import RecordingAuditRepository


class AuditInput(BaseModel):
    value: str


class AuditOutput(BaseModel):
    value: str


def metadata(name: str) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        version="1.0.0",
        description="Audit orchestration test tool.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("audit_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
    )


def context() -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        customer_id=uuid4(),
        conversation_id=uuid4(),
        model_run_id=uuid4(),
    )


def executor_for(tool_class: type[BaseTool]):
    registry = ToolRegistry()
    registry.register(tool_class)
    audit = RecordingAuditRepository()
    return ToolExecutor(registry, audit), audit


def test_success_creates_and_completes_exactly_one_audit_record() -> None:
    class SuccessfulTool(BaseTool[AuditInput, AuditOutput]):
        metadata = metadata("audit_success")
        input_schema = AuditInput
        output_schema = AuditOutput

        def execute(self, context, input_model):
            return ToolResult[AuditOutput](
                status=ToolStatus.SUCCESS,
                data=AuditOutput(value=input_model.value),
            )

    executor, audit = executor_for(SuccessfulTool)
    execution_context = context()

    executor.execute(
        "audit_success",
        "1.0.0",
        execution_context,
        AuditInput(value="ok"),
    )

    assert len(audit.started) == 1
    assert len(audit.finalized) == 1
    assert audit.started[0]["context"] is execution_context
    assert audit.started[0]["tool_name"] == "audit_success"
    assert audit.started[0]["tool_version"] == "1.0.0"
    assert audit.started[0]["input_truncated"] is False
    assert audit.finalized[0]["tool_call_id"] == audit.started[0]["tool_call_id"]
    assert audit.finalized[0]["status"] == "completed"
    assert audit.finalized[0]["success"] is True
    assert audit.finalized[0]["output_truncated"] is False
    assert audit.finalized[0]["finished_at"] is not None
    assert audit.finalized[0]["duration_ms"] >= 0


def test_business_failure_records_failed_status_and_error_code() -> None:
    class FailingTool(BaseTool[AuditInput, AuditOutput]):
        metadata = metadata("audit_failure")
        input_schema = AuditInput
        output_schema = AuditOutput

        def execute(self, context, input_model):
            return ToolResult[AuditOutput](
                status=ToolStatus.FAILURE,
                error=ToolError(
                    error_code="expected_failure",
                    public_message="The request could not be completed.",
                ),
            )

    executor, audit = executor_for(FailingTool)

    result = executor.execute(
        "audit_failure", "1.0.0", context(), AuditInput(value="fail")
    )

    assert result.status is ToolStatus.FAILURE
    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "failed"
    assert audit.finalized[0]["success"] is False
    assert audit.finalized[0]["error_code"] == "expected_failure"
    assert audit.finalized[0]["exception_type"] is None


def test_unexpected_exception_is_recorded_and_propagated() -> None:
    class ExplodingTool(BaseTool[AuditInput, AuditOutput]):
        metadata = metadata("audit_error")
        input_schema = AuditInput
        output_schema = AuditOutput

        def execute(self, context, input_model):
            raise ValueError("unexpected test failure")

    executor, audit = executor_for(ExplodingTool)

    with pytest.raises(ValueError, match="unexpected test failure"):
        executor.execute(
            "audit_error", "1.0.0", context(), AuditInput(value="explode")
        )

    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "error"
    assert audit.finalized[0]["success"] is False
    assert audit.finalized[0]["exception_type"] == "ValueError"
    assert audit.finalized[0]["duration_ms"] >= 0


def test_execution_ids_are_distinct_across_executions() -> None:
    class RepeatableTool(BaseTool[AuditInput, AuditOutput]):
        metadata = metadata("audit_unique")
        input_schema = AuditInput
        output_schema = AuditOutput

        def execute(self, context, input_model):
            return ToolResult[AuditOutput](
                status=ToolStatus.SUCCESS,
                data=AuditOutput(value=input_model.value),
            )

    executor, audit = executor_for(RepeatableTool)
    first_context = context()
    second_context = context()

    executor.execute(
        "audit_unique", "1.0.0", first_context, AuditInput(value="first")
    )
    executor.execute(
        "audit_unique", "1.0.0", second_context, AuditInput(value="second")
    )

    execution_ids = [record["context"].execution_id for record in audit.started]
    assert execution_ids == [
        first_context.execution_id,
        second_context.execution_id,
    ]
    assert len(set(execution_ids)) == 2
