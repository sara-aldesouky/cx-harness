"""Payment model relationships, constraints, and cascades."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.database.models import Order, Payment, PaymentEvent
from tests.models.factories import (
    create_customer,
    create_order,
    create_payment,
    create_payment_event,
)


def rejected(session, instance) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SQLAlchemyError):
        with session.begin_nested():
            session.add(instance)
            session.flush()


def test_order_has_payment_attempts_with_events(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    payment = create_payment(db_session, order)
    event = create_payment_event(db_session, payment)

    db_session.expire_all()

    assert db_session.get(Order, order.id).payments == [payment]
    assert db_session.get(Payment, payment.id).events == [event]
    assert db_session.get(PaymentEvent, event.id).payment == payment


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "unknown"),
        ("method_type", "processor_secret"),
        ("amount", Decimal("-0.01")),
        ("currency", "EGPX"),
    ],
)
def test_invalid_payment_values_are_rejected(db_session, field, value) -> None:
    order = create_order(db_session, create_customer(db_session))
    values = {
        "order_id": order.id,
        "status": "succeeded",
        "method_type": "card",
        "amount": Decimal("10.00"),
        "currency": "EGP",
    }
    values[field] = value

    rejected(db_session, Payment(**values))


def test_invalid_payment_event_type_is_rejected(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    payment = create_payment(db_session, order)
    rejected(
        db_session,
        PaymentEvent(
            payment_id=payment.id,
            event_type="processor_debug",
            public_description="Invalid",
            occurred_at=datetime.now(timezone.utc),
        ),
    )


def test_order_delete_cascades_payments_and_events(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    payment = create_payment(db_session, order)
    event = create_payment_event(db_session, payment)
    payment_id, event_id = payment.id, event.id

    db_session.execute(delete(Order).where(Order.id == order.id))
    db_session.flush()
    db_session.expire_all()

    assert db_session.get(Payment, payment_id) is None
    assert db_session.get(PaymentEvent, event_id) is None
