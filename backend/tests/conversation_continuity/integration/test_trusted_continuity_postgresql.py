"""Local PostgreSQL verification of trusted continuity and re-verification."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.argument_binding import TrustedArgumentBinder
from app.conversation_continuity import TrustedConversationEntityContinuityService
from app.database.models import Customer, Order
from app.entity_resolution import OrderEntityResolver
from app.services.order_resolution_runtime_repository import (
    SessionFactoryOrderResolutionRepository,
)
from app.services.trusted_argument_binding_runtime import (
    TrustedSelectionPipeline,
    build_runtime_binding_policy_registry,
)
from app.tools.context import ExecutionContext
from app.tools.execution_request import ToolExecutionRequest
from app.tools.write_capabilities import CancelOrderTool
from app.tools.registry import ToolRegistry
from app.tools.result import ToolResult, ToolStatus
from app.tools.selection import ToolSelectionRequest, ToolSelectionResolver
from tests.conversation_continuity.test_trusted_entity_continuity import Output


pytestmark = pytest.mark.integration


def test_trusted_reference_is_reverified_in_local_postgresql(test_session_factory):
    customer_id, conversation_id = uuid4(), uuid4()
    with test_session_factory.begin() as session:
        session.add(Customer(
            id=customer_id, first_name="Continuity", last_name="Test",
            phone=f"+20-{str(customer_id)[:12]}", email=f"{customer_id}@example.test",
            preferred_language="en", is_active=True,
        ))
        session.add(Order(
            id=uuid4(), order_number="ORD-15021", customer_id=customer_id,
            status="preparing", payment_status="paid",
            total_amount=Decimal("50.00"), delivery_address="Test address",
            estimated_delivery_time=datetime.now(timezone.utc),
        ))
    try:
        context = ExecutionContext(
            trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id,
            conversation_id=conversation_id, model_name="qwen3:8b",
        )
        continuity = TrustedConversationEntityContinuityService(
            order_tool_names={"cancel_order"}
        )
        continuity.record_success(
            ToolExecutionRequest(
                call_id="trusted-source", tool_name="get_order_details",
                tool_version="1.0.0", arguments={"order_number": "ORD-15021"},
                context=context,
            ),
            ToolResult(
                status=ToolStatus.SUCCESS,
                data=Output(order_number="ORD-15021"),
            ),
            1,
        )
        registry = ToolRegistry()
        registry.register(CancelOrderTool)
        policies = build_runtime_binding_policy_registry(registry)
        pipeline = TrustedSelectionPipeline(
            TrustedArgumentBinder(
                policies,
                OrderEntityResolver(
                    SessionFactoryOrderResolutionRepository(test_session_factory)
                ),
                known_tool_names={"cancel_order"},
            ),
            ToolSelectionResolver(registry),
            continuity_service=continuity,
        )
        selected = pipeline.bind_and_validate(
            ToolSelectionRequest(
                call_id="provider-call", tool_name="cancel_order",
                tool_version="1.0.0",
                arguments={"order_number": "ORD-99999"},
            ),
            context,
            "check that order",
            source_turn=2,
        )
        assert dict(selected.arguments) == {"order_number": "ORD-15021"}
    finally:
        with test_session_factory.begin() as session:
            session.execute(delete(Order).where(Order.customer_id == customer_id))
            session.execute(delete(Customer).where(Customer.id == customer_id))
