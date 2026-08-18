"""Real PostgreSQL verification of atomic refund initiation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.database.models import Customer, Order, Refund, RefundEvent
from app.tools.context import ExecutionContext
from app.write_operations import (
    InitiateRefundInput,
    InitiateRefundOperation,
    SQLAlchemyRefundInitiationReader,
    SQLAlchemyRefundInitiationStore,
    SQLAlchemyTransactionManager,
    WriteExecutionContext,
    WriteFrameworkExecutor,
    WriteSecurityEnvelope,
    WriteStatus,
)
from tests.models.factories import (
    create_customer,
    create_order,
    create_payment,
    create_refund_eligibility,
)


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


def test_postgresql_refund_request_event_and_duplicate_prevention(test_session_factory) -> None:
    suffix = uuid4().hex[:10].upper()
    order_id = customer_id = payment_id = None
    with test_session_factory() as setup:
        customer = create_customer(
            setup,
            email=f"refund-write-{suffix.lower()}@example.test",
            phone=f"+205{suffix.lower()}",
        )
        order = create_order(
            setup, customer, order_number=f"REFUND-{suffix}",
            status="delivered", payment_status="paid",
        )
        payment = create_payment(setup, order, status="succeeded", currency="EGP")
        create_refund_eligibility(setup, order, status="eligible")
        customer_id, order_id, payment_id = customer.id, order.id, payment.id
        order_number = order.order_number
        setup.commit()

    try:
        operation = InitiateRefundOperation(
            SQLAlchemyRefundInitiationReader(test_session_factory),
            SQLAlchemyRefundInitiationStore,
        )
        executor = WriteFrameworkExecutor(SQLAlchemyTransactionManager(test_session_factory))
        request = InitiateRefundInput(order_number=order_number)
        first = executor.execute(operation, context(customer_id), request)
        second = executor.execute(operation, context(customer_id), request)

        assert first.status is WriteStatus.SUCCESS
        assert first.outcome.request_created is True
        assert second.error.error_code == "refund_already_requested"
        with test_session_factory() as verify:
            refunds = verify.scalar(
                select(func.count()).select_from(Refund).where(Refund.payment_id == payment_id)
            )
            events = verify.scalar(
                select(func.count()).select_from(RefundEvent)
                .join(RefundEvent.refund).where(Refund.payment_id == payment_id)
            )
            persisted = verify.scalar(
                select(Refund).where(Refund.payment_id == payment_id)
            )
            assert refunds == 1
            assert events == 1
            assert persisted.status == "pending"
            assert persisted.amount is None
            assert persisted.processed_at is None
    finally:
        if order_id is not None and customer_id is not None:
            with test_session_factory.begin() as cleanup:
                cleanup.execute(delete(Order).where(Order.id == order_id))
                cleanup.execute(delete(Customer).where(Customer.id == customer_id))
