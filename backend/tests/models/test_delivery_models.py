"""Delivery model relationships, constraints, and cascades."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.database.models import Delivery, DeliveryEvent, Order
from tests.models.factories import (
    create_customer,
    create_delivery,
    create_delivery_event,
    create_order,
)


def test_order_has_one_delivery_with_ordered_events(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    delivery = create_delivery(db_session, order)
    event = create_delivery_event(db_session, delivery)

    db_session.expire_all()

    assert db_session.get(Order, order.id).delivery.id == delivery.id
    assert db_session.get(Delivery, delivery.id).events == [event]
    assert db_session.get(DeliveryEvent, event.id).delivery.id == delivery.id


def test_duplicate_delivery_for_order_is_rejected(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    create_delivery(db_session, order)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Delivery(order_id=order.id, status="scheduled"))
            db_session.flush()


@pytest.mark.parametrize("status", ["unknown", "in_transit"])
def test_invalid_delivery_status_is_rejected(db_session, status) -> None:
    order = create_order(db_session, create_customer(db_session))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Delivery(order_id=order.id, status=status))
            db_session.flush()


def test_invalid_delivery_window_is_rejected(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    start = datetime.now(timezone.utc)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Delivery(
                    order_id=order.id,
                    status="scheduled",
                    window_start=start,
                    window_end=start - timedelta(hours=1),
                )
            )
            db_session.flush()


def test_invalid_delivery_event_type_is_rejected(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    delivery = create_delivery(db_session, order)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                DeliveryEvent(
                    delivery_id=delivery.id,
                    event_type="private_internal_event",
                    public_description="Invalid",
                    occurred_at=datetime.now(timezone.utc),
                )
            )
            db_session.flush()


def test_deleting_order_cascades_delivery_and_events(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    delivery = create_delivery(db_session, order)
    event = create_delivery_event(db_session, delivery)
    delivery_id, event_id = delivery.id, event.id

    db_session.execute(delete(Order).where(Order.id == order.id))
    db_session.flush()
    db_session.expire_all()

    assert db_session.get(Delivery, delivery_id) is None
    assert db_session.get(DeliveryEvent, event_id) is None
