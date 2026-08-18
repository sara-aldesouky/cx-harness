"""Pure contract and safety tests for the Stage 12.9 adapter bridge."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.harness.tool_loop_runtime import DEFAULT_BUSINESS_TOOL_CLASSES
from app.tools import PingTool, ToolRegistry, ToolStatus
from app.tools.context import ExecutionContext
from app.tools.security_approval import (
    ToolExecutionSecurityApproval,
    approved_tool_execution,
    current_tool_execution_approval,
)
from app.tools.write_capabilities import (
    WRITE_TOOL_CLASSES,
    CancelOrderTool,
    CreateSupportTicketTool,
    InitiateRefundTool,
    UpdateDeliveryAddressTool,
    WriteToolFactory,
)
from app.write_operations import (
    CancelOrderInput,
    CreateSupportTicketInput,
    InitiateRefundInput,
    UpdateDeliveryAddressInput,
)


def context(*, customer=True):
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        conversation_id=uuid4(),
        customer_id=uuid4() if customer else None,
        principal_role="customer",
    )


def test_runtime_registers_all_writes_without_replacing_read_tools() -> None:
    names = [tool.metadata.name for tool in DEFAULT_BUSINESS_TOOL_CLASSES]
    assert len(names) == len(set(names))
    assert {tool.metadata.name for tool in WRITE_TOOL_CLASSES}.issubset(names)
    assert "get_order_status" in names
    assert "get_customer_profile" in names
    assert all(not tool.metadata.is_read_only for tool in WRITE_TOOL_CLASSES)


@pytest.mark.parametrize("tool_class", WRITE_TOOL_CLASSES)
def test_write_tool_definitions_exclude_trusted_and_internal_fields(tool_class) -> None:
    properties = tool_class.definition()["input_schema"]["properties"]
    forbidden = {
        "customer_id", "conversation_id", "trace_id", "execution_id",
        "request_id", "correlation_id", "security", "payment_id",
        "refund_status", "settlement_amount", "ticket_status", "priority",
        "assigned_agent_id", "internal_notes",
    }
    assert forbidden.isdisjoint(properties)
    assert tool_class.input_schema.model_config.get("extra") == "forbid"
    assert tool_class.input_schema.model_config.get("frozen") is True


@pytest.mark.parametrize(
    ("tool", "input_model"),
    [
        (CancelOrderTool, CancelOrderInput(order_number="ORD-10025")),
        (
            UpdateDeliveryAddressTool,
            UpdateDeliveryAddressInput(
                order_number="ORD-10025", delivery_address="١٢ شارع النيل, القاهرة"
            ),
        ),
        (InitiateRefundTool, InitiateRefundInput(order_number="ORD-10025")),
        (
            CreateSupportTicketTool,
            CreateSupportTicketInput(
                category="order_issue",
                issue_description="el moshkela mat7aletsh w 3ayz akalem support",
                escalation_reason="unresolved_issue",
                order_number="ORD-10025",
            ),
        ),
    ],
)
def test_write_tools_fail_closed_without_gateway_approval(tool, input_model) -> None:
    instance = object.__new__(tool)
    result = instance.execute(context(), input_model)
    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "write_security_not_approved"


def test_incomplete_approval_fails_closed_and_scope_is_cleaned_up() -> None:
    approval = ToolExecutionSecurityApproval(
        authenticated=True,
        role_policy_allowed=True,
        tool_authorized=False,
        ownership_authorized=True,
    )
    instance = object.__new__(CancelOrderTool)
    with approved_tool_execution(approval):
        result = instance.execute(context(), CancelOrderInput(order_number="ORD-10025"))
        assert current_tool_execution_approval() is approval
    assert result.error.error_code == "write_security_not_approved"
    assert current_tool_execution_approval() is None


def test_missing_identity_fails_closed_even_with_complete_approval() -> None:
    approval = ToolExecutionSecurityApproval(
        authenticated=True,
        role_policy_allowed=True,
        tool_authorized=True,
        ownership_authorized=True,
    )
    instance = object.__new__(CancelOrderTool)
    with approved_tool_execution(approval):
        result = instance.execute(
            context(customer=False), CancelOrderInput(order_number="ORD-10025")
        )
    assert result.error.error_code == "customer_identity_required"


def test_unexpected_adapter_failure_returns_safe_tool_failure(monkeypatch) -> None:
    approval = ToolExecutionSecurityApproval(
        authenticated=True,
        role_policy_allowed=True,
        tool_authorized=True,
        ownership_authorized=True,
    )
    instance = object.__new__(CancelOrderTool)
    monkeypatch.setattr(
        instance,
        "_build_operation",
        lambda: (_ for _ in ()).throw(RuntimeError("private dependency detail")),
    )
    with approved_tool_execution(approval):
        result = instance.execute(
            context(), CancelOrderInput(order_number="ORD-10025")
        )
    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "write_adapter_unavailable"
    assert "private" not in result.model_dump_json()


def test_model_cannot_inject_identity_or_internal_write_fields() -> None:
    with pytest.raises(ValidationError):
        CancelOrderInput(order_number="ORD-10025", customer_id=str(uuid4()))
    with pytest.raises(ValidationError):
        InitiateRefundInput(order_number="ORD-10025", payment_id=str(uuid4()))
    with pytest.raises(ValidationError):
        CreateSupportTicketInput(
            category="order_issue",
            issue_description="A sufficiently detailed customer support issue.",
            escalation_reason="unresolved_issue",
            priority="critical",
        )


def test_write_tool_factory_injects_only_write_tools() -> None:
    class Factory:
        def __call__(self):
            return None

    dependency = Factory()
    factory = WriteToolFactory(dependency)
    write_tool = factory(CancelOrderTool)
    read_tool = factory(PingTool)
    assert isinstance(write_tool, CancelOrderTool)
    assert write_tool._session_factory is dependency
    assert isinstance(read_tool, PingTool)


def test_security_approval_contract_rejects_invalid_scope_input() -> None:
    with pytest.raises(TypeError):
        with approved_tool_execution(object()):
            pass
