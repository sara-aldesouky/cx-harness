"""Pure tests for centralized, provider-independent role policy."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.authentication import HMACCustomerAuthenticator
from app.role_policy import (
    CapabilityRolePolicyService,
    PrincipalRole,
    RolePolicyDecision,
    RolePolicyError,
    RolePolicyFailureCode,
)
from app.tools.context import ExecutionContext
from app.tools.contracts import GroundingCapability, ToolCategory, ToolMetadata
from app.tools.execution_gateway import SingleToolExecutionGateway
from app.tools.execution_request import ToolExecutionRequest
from app.tools.executor import ToolExecutor
from app.tools.get_order_status import GetOrderStatusTool
from app.tools.registry import ToolRegistry
from app.tools.result import ToolStatus
from tests.tools.audit_fakes import RecordingAuditRepository


def metadata(
    capability=GroundingCapability.ORDER,
    *,
    category=ToolCategory.ORDER,
) -> ToolMetadata:
    capabilities = () if capability is None else (capability,)
    return ToolMetadata(
        name="role_test_tool",
        version="1.0.0",
        description="Role policy test tool.",
        category=category,
        supported_use_cases=("role_policy_test",),
        grounding_capabilities=capabilities,
        requires_customer_identity=category is not ToolCategory.SYSTEM,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
    )


@pytest.mark.parametrize(
    "role",
    [
        PrincipalRole.CUSTOMER,
        PrincipalRole.CUSTOMER_SUPPORT_AGENT,
        PrincipalRole.SUPERVISOR,
        PrincipalRole.ADMINISTRATOR,
        PrincipalRole.INTERNAL_SYSTEM,
    ],
)
@pytest.mark.parametrize("capability", tuple(GroundingCapability))
def test_supported_roles_can_use_declared_read_capabilities(role, capability) -> None:
    decision = CapabilityRolePolicyService().evaluate(role, metadata(capability))
    assert decision.allowed is True


@pytest.mark.parametrize("role", tuple(PrincipalRole))
def test_customer_facing_knowledge_is_not_unnecessarily_restricted(role) -> None:
    decision = CapabilityRolePolicyService().evaluate(
        role,
        metadata(GroundingCapability.KNOWLEDGE, category=ToolCategory.POLICY),
    )
    assert decision.allowed is True


def test_only_internal_system_role_can_use_unclassified_system_tool() -> None:
    policy = CapabilityRolePolicyService()
    system_metadata = metadata(None, category=ToolCategory.SYSTEM)

    denied = policy.evaluate(PrincipalRole.CUSTOMER, system_metadata)
    allowed = policy.evaluate(PrincipalRole.INTERNAL_SYSTEM, system_metadata)

    assert denied.failure_code is RolePolicyFailureCode.INSUFFICIENT_ROLE
    assert allowed.allowed is True


def test_unknown_role_is_structured_and_does_not_fall_back() -> None:
    with pytest.raises(RolePolicyError) as caught:
        CapabilityRolePolicyService().evaluate("super-admin", metadata())
    assert caught.value.code is RolePolicyFailureCode.UNKNOWN_ROLE


def test_invalid_policy_configuration_fails_closed() -> None:
    with pytest.raises(RolePolicyError) as caught:
        CapabilityRolePolicyService({})
    assert caught.value.code is RolePolicyFailureCode.POLICY_UNAVAILABLE


def test_unclassified_business_capability_fails_closed() -> None:
    decision = CapabilityRolePolicyService().evaluate(
        PrincipalRole.ADMINISTRATOR,
        metadata(None, category=ToolCategory.ORDER),
    )
    assert decision.failure_code is RolePolicyFailureCode.POLICY_EVALUATION_FAILURE


def test_role_policy_decision_is_immutable() -> None:
    decision = RolePolicyDecision.allow()
    with pytest.raises(ValidationError):
        decision.allowed = False  # type: ignore[misc]


def test_role_denial_prevents_execution_and_audit_persistence() -> None:
    registry = ToolRegistry()
    registry.register(GetOrderStatusTool)
    audit = RecordingAuditRepository()
    gateway = SingleToolExecutionGateway(
        registry,
        ToolExecutor(registry, audit),
        role_policy_service=CapabilityRolePolicyService(
            {PrincipalRole.CUSTOMER: frozenset()}
        ),
    )
    request = ToolExecutionRequest(
        call_id="call-role-denied",
        tool_name="get_order_status",
        tool_version="1.0.0",
        arguments={"order_number": "ORD-10025"},
        context=ExecutionContext(
            trace_id=uuid4(),
            execution_id=uuid4(),
            customer_id=uuid4(),
            principal_role=PrincipalRole.CUSTOMER.value,
        ),
    )

    result = gateway.execute(request)

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "insufficient_role"
    assert audit.started == audit.finalized == []


def test_hmac_authentication_cannot_accept_a_caller_selected_role() -> None:
    """The customer token grammar contains identity and expiry, never a role."""

    authenticator = HMACCustomerAuthenticator("x" * 32)
    with pytest.raises(Exception):
        authenticator.authenticate(f"Bearer {uuid4()}.9999999999.administrator.fake")
