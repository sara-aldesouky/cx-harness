"""Real PostgreSQL verification of atomic support-ticket creation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.database.models import Customer, Order, SupportTicket
from app.tools.context import ExecutionContext
from app.write_operations import (
    CreateSupportTicketInput,
    CreateSupportTicketOperation,
    SQLAlchemySupportTicketReader,
    SQLAlchemySupportTicketStore,
    SQLAlchemyTransactionManager,
    WriteExecutionContext,
    WriteFrameworkExecutor,
    WriteSecurityEnvelope,
    WriteStatus,
)
from tests.models.factories import create_customer, create_order


pytestmark = pytest.mark.integration


def context(customer_id):
    return WriteExecutionContext(
        execution_context=ExecutionContext(
            trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id,
            principal_role="customer",
        ),
        security=WriteSecurityEnvelope(
            authenticated=True, role_policy_allowed=True,
            tool_authorized=True, ownership_authorized=True,
        ),
        request_id=uuid4(), correlation_id=uuid4(),
        requested_at=datetime.now(timezone.utc),
    )


def test_postgresql_ticket_creation_and_duplicate_prevention(test_session_factory) -> None:
    suffix = uuid4().hex[:10].upper()
    customer_id = order_id = None
    with test_session_factory() as setup:
        customer = create_customer(
            setup,
            email=f"ticket-{suffix.lower()}@example.test",
            phone=f"+204{suffix.lower()}",
        )
        order = create_order(setup, customer, order_number=f"TICKET-{suffix}")
        customer_id, order_id, order_number = customer.id, order.id, order.order_number
        setup.commit()

    try:
        operation = CreateSupportTicketOperation(
            SQLAlchemySupportTicketReader(test_session_factory),
            SQLAlchemySupportTicketStore,
        )
        executor = WriteFrameworkExecutor(SQLAlchemyTransactionManager(test_session_factory))
        request = CreateSupportTicketInput(
            category="order_issue",
            issue_description="My order issue still needs help from a support specialist.",
            escalation_reason="unresolved_issue",
            order_number=order_number,
        )
        first = executor.execute(operation, context(customer_id), request)
        second = executor.execute(operation, context(customer_id), request)

        assert first.status is WriteStatus.SUCCESS
        assert first.outcome.ticket_created is True
        assert first.outcome.ticket_reference.startswith("TKT-")
        assert second.error.error_code == "support_ticket_already_exists"
        with test_session_factory() as verify:
            count = verify.scalar(
                select(func.count()).select_from(SupportTicket).where(
                    SupportTicket.customer_id == customer_id
                )
            )
            ticket = verify.scalar(
                select(SupportTicket).where(SupportTicket.customer_id == customer_id)
            )
            assert count == 1
            assert ticket.related_order_id == order_id
            assert ticket.status == "open"
            assert ticket.priority == "medium"
    finally:
        if customer_id is not None:
            with test_session_factory.begin() as cleanup:
                cleanup.execute(
                    delete(SupportTicket).where(SupportTicket.customer_id == customer_id)
                )
                if order_id is not None:
                    cleanup.execute(delete(Order).where(Order.id == order_id))
                cleanup.execute(delete(Customer).where(Customer.id == customer_id))
