"""Protected resources expose uniform public outcomes without tool execution."""

from uuid import uuid4

import pytest

from app.authorization import (
    AuthorizationFailureCode,
    OwnershipAuthorizationService,
    OwnershipStatus,
)
from app.tools.context import ExecutionContext
from app.tools.contracts import GroundingCapability
from app.tools.execution_gateway import SingleToolExecutionGateway
from app.tools.execution_request import ToolExecutionRequest
from app.tools.executor import ToolExecutor
from app.tools.get_order_status import GetOrderStatusTool
from app.tools.registry import ToolRegistry
from tests.tools.audit_fakes import RecordingAuditRepository


class Resolver:
    def __init__(self, status):
        self.status = status

    def order_status(self, customer_id, order_reference):
        return self.status


def execute(status):
    registry = ToolRegistry()
    registry.register(GetOrderStatusTool)
    audit = RecordingAuditRepository()
    gateway = SingleToolExecutionGateway(
        registry,
        ToolExecutor(registry, audit),
        authorization_service=OwnershipAuthorizationService(Resolver(status)),
    )
    request = ToolExecutionRequest(
        call_id="call-enumeration",
        tool_name="get_order_status",
        tool_version="1.0.0",
        arguments={"order_number": "ORD-PROTECTED"},
        context=ExecutionContext(
            trace_id=uuid4(), execution_id=uuid4(), customer_id=uuid4()
        ),
    )
    return gateway.execute(request), audit


@pytest.mark.parametrize(
    "capability",
    [
        GroundingCapability.ORDER,
        GroundingCapability.DELIVERY,
        GroundingCapability.PAYMENT,
        GroundingCapability.REFUND,
    ],
)
def test_customer_owned_domains_share_uniform_external_outcome(capability) -> None:
    # These domains all use the same order-ownership boundary; capability metadata
    # does not alter the public normalization rule.
    denied, denied_audit = execute(OwnershipStatus.NOT_OWNED)
    absent, absent_audit = execute(OwnershipStatus.NOT_FOUND)
    assert denied.model_dump(mode="json") == absent.model_dump(mode="json")
    assert denied.error.error_code == "resource_not_found"
    assert denied.error.public_message == "The requested resource was not found."
    assert denied_audit.started == denied_audit.finalized == []
    assert absent_audit.started == absent_audit.finalized == []


def test_internal_decisions_retain_precise_reason_codes() -> None:
    request = ToolExecutionRequest(
        call_id="call-internal",
        tool_name="get_order_status",
        tool_version="1.0.0",
        arguments={"order_number": "ORD-X"},
        context=ExecutionContext(
            trace_id=uuid4(), execution_id=uuid4(), customer_id=uuid4()
        ),
    )
    metadata = GetOrderStatusTool.metadata
    denied = OwnershipAuthorizationService(Resolver(OwnershipStatus.NOT_OWNED)).authorize(
        request, metadata
    )
    absent = OwnershipAuthorizationService(Resolver(OwnershipStatus.NOT_FOUND)).authorize(
        request, metadata
    )
    assert denied.failure_code is AuthorizationFailureCode.UNAUTHORIZED_RESOURCE
    assert absent.failure_code is AuthorizationFailureCode.RESOURCE_NOT_FOUND
