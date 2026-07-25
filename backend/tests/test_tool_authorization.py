"""Tests for exact-tool policy registration and authorization."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.identity_roles import PrincipalRole
from app.tool_authorization import (
    CentralToolAuthorizationService,
    ToolAuthorizationDecision,
    ToolAuthorizationFailureCode,
    ToolAuthorizationPolicyError,
    ToolPermission,
    ToolPolicyRegistry,
)
from app.tools.context import ExecutionContext
from app.tools.execution_gateway import SingleToolExecutionGateway
from app.tools.execution_request import ToolExecutionRequest
from app.tools.executor import ToolExecutor
from app.tools.get_order_status import GetOrderStatusTool
from app.tools.ping import PingTool
from app.tools.registry import ToolRegistry
from app.tools.result import ToolStatus
from tests.tools.audit_fakes import RecordingAuditRepository


def runtime_registry(*tools) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


@pytest.mark.parametrize(
    "role",
    [
        PrincipalRole.CUSTOMER,
        PrincipalRole.CUSTOMER_SUPPORT_AGENT,
        PrincipalRole.SUPERVISOR,
        PrincipalRole.ADMINISTRATOR,
    ],
)
def test_approved_business_tool_permissions(role) -> None:
    registry = ToolPolicyRegistry.for_runtime(
        runtime_registry(GetOrderStatusTool)
    )
    decision = CentralToolAuthorizationService(registry).authorize_tool(
        role, "get_order_status", "1.0.0"
    )
    assert decision.allowed is True


def test_internal_system_is_restricted_to_internal_system_tools() -> None:
    registry = ToolPolicyRegistry.for_runtime(
        runtime_registry(GetOrderStatusTool, PingTool)
    )
    service = CentralToolAuthorizationService(registry)

    business = service.authorize_tool(
        PrincipalRole.INTERNAL_SYSTEM, "get_order_status", "1.0.0"
    )
    system = service.authorize_tool(
        PrincipalRole.INTERNAL_SYSTEM, "ping", "1.0.0"
    )

    assert business.failure_code is ToolAuthorizationFailureCode.TOOL_NOT_PERMITTED
    assert system.allowed is True


def test_customer_cannot_execute_internal_system_tool() -> None:
    registry = ToolPolicyRegistry.for_runtime(runtime_registry(PingTool))
    decision = CentralToolAuthorizationService(registry).authorize_tool(
        PrincipalRole.CUSTOMER, "ping", "1.0.0"
    )
    assert decision.failure_code is ToolAuthorizationFailureCode.TOOL_NOT_PERMITTED


def test_unknown_tool_has_structured_failure() -> None:
    with pytest.raises(ToolAuthorizationPolicyError) as caught:
        CentralToolAuthorizationService(ToolPolicyRegistry()).authorize_tool(
            PrincipalRole.CUSTOMER, "missing", "1.0.0"
        )
    assert caught.value.code is ToolAuthorizationFailureCode.UNKNOWN_TOOL


def test_known_tool_without_policy_fails_closed() -> None:
    registry = ToolPolicyRegistry()
    registry.register_tool(GetOrderStatusTool.metadata)
    with pytest.raises(ToolAuthorizationPolicyError) as caught:
        CentralToolAuthorizationService(registry).authorize_tool(
            PrincipalRole.CUSTOMER, "get_order_status", "1.0.0"
        )
    assert caught.value.code is ToolAuthorizationFailureCode.UNKNOWN_POLICY


def test_policy_registry_discovery_is_deterministic_and_immutable() -> None:
    registry = ToolPolicyRegistry.for_runtime(
        runtime_registry(PingTool, GetOrderStatusTool)
    )
    first = registry.permissions()
    second = registry.permissions()

    assert first == second
    assert tuple(item.tool_name for item in first) == ("get_order_status", "ping")
    with pytest.raises(ValidationError):
        first[0].tool_name = "changed"  # type: ignore[misc]


def test_duplicate_policy_registration_is_rejected() -> None:
    registry = ToolPolicyRegistry()
    registry.register_tool(GetOrderStatusTool.metadata)
    permission = ToolPermission(
        tool_name="get_order_status",
        tool_version="1.0.0",
        allowed_roles=frozenset({PrincipalRole.CUSTOMER}),
    )
    registry.set_policy(permission)
    with pytest.raises(ValueError, match="already assigned"):
        registry.set_policy(permission)


def test_invalid_role_cannot_escalate_to_a_permitted_tool() -> None:
    registry = ToolPolicyRegistry.for_runtime(runtime_registry(GetOrderStatusTool))
    with pytest.raises(ToolAuthorizationPolicyError) as caught:
        CentralToolAuthorizationService(registry).authorize_tool(
            "administrator-plus", "get_order_status", "1.0.0"
        )
    assert caught.value.code is ToolAuthorizationFailureCode.TOOL_NOT_PERMITTED


def test_authorization_service_failure_is_structured() -> None:
    class BrokenRegistry(ToolPolicyRegistry):
        def get(self, tool_name, tool_version):
            raise RuntimeError("internal policy storage detail")

    with pytest.raises(ToolAuthorizationPolicyError) as caught:
        CentralToolAuthorizationService(BrokenRegistry()).authorize_tool(
            PrincipalRole.CUSTOMER, "get_order_status", "1.0.0"
        )
    assert caught.value.code is ToolAuthorizationFailureCode.AUTHORIZATION_UNAVAILABLE
    assert "storage" not in caught.value.public_message


def test_denied_tool_never_executes_or_creates_audit_record() -> None:
    tool_registry = runtime_registry(PingTool)
    audit = RecordingAuditRepository()
    gateway = SingleToolExecutionGateway(
        tool_registry,
        ToolExecutor(tool_registry, audit),
        tool_authorization_service=CentralToolAuthorizationService(
            ToolPolicyRegistry.for_runtime(tool_registry)
        ),
    )
    request = ToolExecutionRequest(
        call_id="call-denied",
        tool_name="ping",
        tool_version="1.0.0",
        arguments={"message": "hello"},
        context=ExecutionContext(
            trace_id=uuid4(),
            execution_id=uuid4(),
            customer_id=uuid4(),
            principal_role=PrincipalRole.CUSTOMER.value,
        ),
    )

    result = gateway.execute(request)

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "tool_not_permitted"
    assert audit.started == audit.finalized == []


def test_permission_and_decision_contracts_are_immutable() -> None:
    permission = ToolPermission(
        tool_name="ping",
        tool_version="1.0.0",
        allowed_roles=frozenset({PrincipalRole.INTERNAL_SYSTEM}),
    )
    decision = ToolAuthorizationDecision.allow()
    with pytest.raises(ValidationError):
        permission.allowed_roles = frozenset()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        decision.allowed = False  # type: ignore[misc]
