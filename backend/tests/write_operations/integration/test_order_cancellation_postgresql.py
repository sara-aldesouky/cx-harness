"""Isolated PostgreSQL verification for transactional order cancellation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.models import Customer, Order
from app.tools.context import ExecutionContext
from app.write_operations import (
    CancelOrderInput,
    CancelOrderOperation,
    SQLAlchemyOrderCancellationReader,
    SQLAlchemyOrderCancellationStore,
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


def test_real_postgresql_commit_and_idempotent_repeat(test_session_factory) -> None:
    suffix = uuid4().hex[:10]
    with test_session_factory() as setup:
        customer = create_customer(
            setup, email=f"cancel-{suffix}@example.test", phone=f"+207{suffix}"
        )
        order = create_order(
            setup, customer, order_number=f"CANCEL-{suffix.upper()}", status="confirmed"
        )
        customer_id, order_id, order_number = customer.id, order.id, order.order_number
        setup.commit()

    try:
        operation = CancelOrderOperation(
            SQLAlchemyOrderCancellationReader(test_session_factory),
            SQLAlchemyOrderCancellationStore,
        )
        executor = WriteFrameworkExecutor(SQLAlchemyTransactionManager(test_session_factory))
        first = executor.execute(operation, context(customer_id), CancelOrderInput(order_number=order_number))
        second = executor.execute(operation, context(customer_id), CancelOrderInput(order_number=order_number))

        assert first.status is WriteStatus.SUCCESS
        assert second.error.error_code == "order_already_cancelled"
        with test_session_factory() as verify:
            persisted = verify.scalar(select(Order).where(Order.id == order_id))
            assert persisted.status == "cancelled"
            assert persisted.updated_at == first.outcome.cancelled_at
    finally:
        with test_session_factory.begin() as cleanup:
            cleanup.execute(delete(Order).where(Order.id == order_id))
            cleanup.execute(delete(Customer).where(Customer.id == customer_id))
