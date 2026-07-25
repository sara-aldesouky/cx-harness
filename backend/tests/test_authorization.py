"""Pure authorization-policy tests with no provider or database dependency."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.authorization import (
    AuthorizationDecision,
    AuthorizationError,
    AuthorizationFailureCode,
    OwnershipAuthorizationService,
    OwnershipStatus,
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


class Resolver:
    def __init__(self, status=OwnershipStatus.OWNED, error=None) -> None:
        self.status = status
        self.error = error
        self.calls = []

    def order_status(self, customer_id, order_number):
        self.calls.append((customer_id, order_number))
        if self.error:
            raise self.error
        return self.status


def context(customer_id=None) -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        customer_id=customer_id,
    )


def request(arguments, customer_id=None) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        call_id="call-001",
        tool_name="business_tool",
        tool_version="1.0.0",
        arguments=arguments,
        context=context(customer_id),
    )


def metadata(
    capability,
    *,
    category=ToolCategory.ORDER,
    identity=True,
    order_ownership=False,
) -> ToolMetadata:
    return ToolMetadata(
        name="business_tool",
        version="1.0.0",
        description="Authorization test capability.",
        category=category,
        supported_use_cases=("authorization_test",),
        grounding_capabilities=(capability,),
        requires_customer_identity=identity,
        requires_order_ownership=order_ownership,
        requires_policy_check=False,
        is_read_only=True,
    )


def test_customer_may_access_own_profile_scope() -> None:
    customer_id = uuid4()
    decision = OwnershipAuthorizationService(Resolver()).authorize(
        request({"request": "profile"}, customer_id),
        metadata(GroundingCapability.CUSTOMER, category=ToolCategory.CUSTOMER),
    )
    assert decision.allowed is True


def test_customer_may_not_access_another_customer_profile() -> None:
    decision = OwnershipAuthorizationService(Resolver()).authorize(
        request({"customer_id": str(uuid4())}, uuid4()),
        metadata(GroundingCapability.CUSTOMER, category=ToolCategory.CUSTOMER),
    )
    assert decision.allowed is False
    assert decision.failure_code is AuthorizationFailureCode.RESOURCE_OWNERSHIP_MISMATCH


@pytest.mark.parametrize(
    "capability",
    [
        GroundingCapability.ORDER,
        GroundingCapability.DELIVERY,
        GroundingCapability.PAYMENT,
        GroundingCapability.REFUND,
    ],
)
def test_owned_transactional_resource_is_allowed(capability) -> None:
    customer_id = uuid4()
    resolver = Resolver(OwnershipStatus.OWNED)
    decision = OwnershipAuthorizationService(resolver).authorize(
        request({"order_number": "ORD-10025"}, customer_id),
        metadata(capability, order_ownership=True),
    )
    assert decision.allowed is True
    assert resolver.calls == [(customer_id, "ORD-10025")]


@pytest.mark.parametrize(
    "capability",
    [GroundingCapability.ORDER, GroundingCapability.REFUND],
)
def test_another_customers_transactional_resource_is_denied(capability) -> None:
    decision = OwnershipAuthorizationService(
        Resolver(OwnershipStatus.NOT_OWNED)
    ).authorize(
        request({"order_number": "ORD-OTHER"}, uuid4()),
        metadata(capability, order_ownership=True),
    )
    assert decision.allowed is False
    assert decision.failure_code is AuthorizationFailureCode.UNAUTHORIZED_RESOURCE


def test_public_knowledge_requires_no_identity_or_ownership_lookup() -> None:
    resolver = Resolver(error=AssertionError("must not query ownership"))
    decision = OwnershipAuthorizationService(resolver).authorize(
        request({"slug": "refund-policy"}),
        metadata(
            GroundingCapability.KNOWLEDGE,
            category=ToolCategory.POLICY,
            identity=False,
        ),
    )
    assert decision.allowed is True
    assert resolver.calls == []


def test_missing_transactional_identity_is_denied() -> None:
    decision = OwnershipAuthorizationService(Resolver()).authorize(
        request({"order_number": "ORD-10025"}),
        metadata(GroundingCapability.ORDER, order_ownership=True),
    )
    assert decision.failure_code is AuthorizationFailureCode.ACCESS_DENIED


def test_missing_protected_resource_is_denied_before_tool_execution() -> None:
    decision = OwnershipAuthorizationService(
        Resolver(OwnershipStatus.NOT_FOUND)
    ).authorize(
        request({"order_number": "ORD-MISSING"}, uuid4()),
        metadata(GroundingCapability.ORDER, order_ownership=True),
    )
    assert decision.allowed is False
    assert decision.failure_code is AuthorizationFailureCode.RESOURCE_NOT_FOUND


def test_authorization_unavailable_is_structured() -> None:
    expected = AuthorizationError(
        AuthorizationFailureCode.AUTHORIZATION_UNAVAILABLE,
        "Authorization is temporarily unavailable.",
    )
    with pytest.raises(AuthorizationError) as caught:
        OwnershipAuthorizationService(Resolver(error=expected)).authorize(
            request({"order_number": "ORD-10025"}, uuid4()),
            metadata(GroundingCapability.ORDER, order_ownership=True),
        )
    assert caught.value is expected


def test_denied_gateway_request_never_executes_or_writes_audit() -> None:
    registry = ToolRegistry()
    registry.register(GetOrderStatusTool)
    audit = RecordingAuditRepository()
    gateway = SingleToolExecutionGateway(
        registry,
        ToolExecutor(registry, audit),
        authorization_service=OwnershipAuthorizationService(
            Resolver(OwnershipStatus.NOT_OWNED)
        ),
    )
    customer_id = uuid4()
    execution_request = ToolExecutionRequest(
        call_id="call-denied",
        tool_name="get_order_status",
        tool_version="1.0.0",
        arguments={"order_number": "ORD-OTHER"},
        context=context(customer_id),
    )

    result = gateway.execute(execution_request)

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "resource_not_found"
    assert result.error.public_message == "The requested resource was not found."
    assert audit.started == audit.finalized == []


def test_authorization_decisions_are_immutable_and_well_formed() -> None:
    decision = AuthorizationDecision.allow()
    with pytest.raises(ValidationError):
        decision.allowed = False  # type: ignore[misc]
    with pytest.raises(ValidationError):
        AuthorizationDecision(allowed=False)
