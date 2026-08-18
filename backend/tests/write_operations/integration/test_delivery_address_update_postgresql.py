"""Real PostgreSQL verification for delivery-address updates."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.database.models import Customer, Order
from app.tools.context import ExecutionContext
from app.write_operations import (
    SQLAlchemyAddressUpdateReader,
    SQLAlchemyAddressUpdateStore,
    SQLAlchemyTransactionManager,
    UpdateDeliveryAddressInput,
    UpdateDeliveryAddressOperation,
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


def test_postgresql_address_update_and_idempotency(test_session_factory) -> None:
    suffix = uuid4().hex[:10].upper()
    order_id = customer_id = None
    with test_session_factory() as setup:
        customer = create_customer(
            setup,
            email=f"address-{suffix.lower()}@example.test",
            phone=f"+206{suffix.lower()}",
        )
        order = create_order(
            setup,
            customer,
            order_number=f"ADDRESS-{suffix}",
            status="preparing",
            delivery_address="1 Original Road, Cairo",
        )
        customer_id, order_id, order_number = customer.id, order.id, order.order_number
        setup.commit()

    try:
        operation = UpdateDeliveryAddressOperation(
            SQLAlchemyAddressUpdateReader(test_session_factory),
            SQLAlchemyAddressUpdateStore,
        )
        executor = WriteFrameworkExecutor(SQLAlchemyTransactionManager(test_session_factory))
        request = UpdateDeliveryAddressInput(
            order_number=order_number, delivery_address="9 Updated Avenue, Giza"
        )
        first = executor.execute(operation, context(customer_id), request)
        second = executor.execute(operation, context(customer_id), request)

        assert first.status is WriteStatus.SUCCESS
        assert first.outcome.address_updated is True
        assert second.error.error_code == "address_already_up_to_date"
        with test_session_factory() as verify:
            persisted = verify.scalar(select(Order).where(Order.id == order_id))
            assert persisted.delivery_address == "9 Updated Avenue, Giza"
            assert persisted.updated_at == first.outcome.updated_at
    finally:
        if order_id is not None and customer_id is not None:
            with test_session_factory.begin() as cleanup:
                cleanup.execute(delete(Order).where(Order.id == order_id))
                cleanup.execute(delete(Customer).where(Customer.id == customer_id))
