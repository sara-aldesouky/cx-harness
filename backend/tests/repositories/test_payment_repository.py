"""Integration tests for deterministic read-only payment queries."""

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.database.models import Order, Payment, PaymentEvent
from app.database.repositories import PaymentRepository
from tests.models.factories import (
    create_customer,
    create_order,
    create_payment,
    create_payment_event,
)


def counts(session) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    return tuple(
        session.scalar(select(func.count()).select_from(model)) or 0
        for model in (Order, Payment, PaymentEvent)
    )


def test_latest_payment_lookup_enforces_customer_and_is_read_only(db_session) -> None:
    customer = create_customer(db_session)
    other = create_customer(db_session)
    order = create_order(db_session, customer, order_number="ORD-40001")
    create_payment(
        db_session,
        order,
        status="failed",
        created_at=datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
    )
    latest = create_payment(
        db_session,
        order,
        status="succeeded",
        created_at=datetime(2026, 1, 1, 11, tzinfo=timezone.utc),
    )
    repository = PaymentRepository(db_session)
    before = counts(db_session)

    assert repository.get_latest_owned_by_order_number(
        "ORD-40001", customer.id
    ).id == latest.id
    assert repository.get_latest_owned_by_order_number(
        "ORD-40001", other.id
    ) is None
    assert counts(db_session) == before


def test_history_spans_attempts_and_orders_events_deterministically(db_session) -> None:
    customer = create_customer(db_session)
    order = create_order(db_session, customer, order_number="ORD-40002")
    first_payment = create_payment(db_session, order, status="failed")
    second_payment = create_payment(db_session, order, status="succeeded")
    first = create_payment_event(
        db_session,
        first_payment,
        event_type="failed",
        occurred_at=datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
    )
    latest = create_payment_event(
        db_session,
        second_payment,
        event_type="captured",
        occurred_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
    )
    repository = PaymentRepository(db_session)

    assert repository.get_latest_event_for_order(
        "ORD-40002", customer.id
    ).id == latest.id
    assert [
        event.id
        for event in repository.list_events_for_order(
            "ORD-40002", customer.id
        )
    ] == [latest.id, first.id]
    assert repository.list_events_for_order(
        "ORD-40002", customer.id, limit=1, offset=1
    )[0].id == first.id
    assert repository.count_events_for_order("ORD-40002", customer.id) == 2
