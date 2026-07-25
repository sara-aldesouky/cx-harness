"""Integration tests for read-only deterministic delivery queries."""

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.database.models import Delivery, DeliveryEvent, Order
from app.database.repositories import DeliveryRepository
from tests.models.factories import (
    create_customer,
    create_delivery,
    create_delivery_event,
    create_order,
)


def counts(session) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    return tuple(
        session.scalar(select(func.count()).select_from(model)) or 0
        for model in (Order, Delivery, DeliveryEvent)
    )


def test_owned_lookup_enforces_customer_and_is_read_only(db_session) -> None:
    customer = create_customer(db_session)
    other = create_customer(db_session)
    order = create_order(db_session, customer, order_number="ORD-20001")
    delivery = create_delivery(db_session, order)
    repository = DeliveryRepository(db_session)
    before = counts(db_session)

    assert repository.get_by_order_number("ORD-20001").id == delivery.id
    assert repository.get_owned_by_order_number("ORD-20001", customer.id).id == delivery.id
    assert repository.get_owned_by_order_number("ORD-20001", other.id) is None
    assert counts(db_session) == before


def test_latest_and_history_are_deterministic(db_session) -> None:
    order = create_order(db_session, create_customer(db_session))
    delivery = create_delivery(db_session, order)
    first = create_delivery_event(
        db_session,
        delivery,
        occurred_at=datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
    )
    latest = create_delivery_event(
        db_session,
        delivery,
        event_type="delivery_attempted",
        public_description="A delivery attempt was made.",
        occurred_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
    )
    repository = DeliveryRepository(db_session)
    before = counts(db_session)

    assert repository.get_latest_event(delivery.id).id == latest.id
    assert [event.id for event in repository.list_events(delivery.id)] == [
        latest.id,
        first.id,
    ]
    assert repository.list_events(delivery.id, limit=1, offset=1)[0].id == first.id
    assert repository.count_events(delivery.id) == 2
    assert counts(db_session) == before
