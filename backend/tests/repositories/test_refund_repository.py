"""Read-only RefundRepository integration tests."""

from datetime import datetime, timezone
from decimal import Decimal

from app.database.repositories import RefundRepository
from tests.models.factories import (
    create_customer, create_order, create_payment, create_refund,
    create_refund_eligibility, create_refund_event,
)


def test_refund_repository_scopes_and_orders_multiple_refunds(db_session):
    owner, stranger = create_customer(db_session), create_customer(db_session)
    order = create_order(db_session, owner)
    payment = create_payment(db_session, order)
    older = create_refund(db_session, payment, amount=Decimal("5"), requested_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
    newer = create_refund(db_session, payment, amount=Decimal("20"), requested_at=datetime(2026, 7, 21, tzinfo=timezone.utc))
    repo = RefundRepository(db_session)
    assert repo.get_latest_owned_by_order_number(order.order_number, owner.id) is newer
    assert repo.list_owned_by_order_number(order.order_number, owner.id) == [newer, older]
    assert repo.count_owned_by_order_number(order.order_number, owner.id) == 2
    assert repo.get_latest_owned_by_order_number(order.order_number, stranger.id) is None


def test_refund_repository_latest_event_and_eligibility(db_session):
    customer = create_customer(db_session)
    order = create_order(db_session, customer)
    refund = create_refund(db_session, create_payment(db_session, order))
    create_refund_event(db_session, refund, occurred_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
    latest = create_refund_event(db_session, refund, event_type="processing", occurred_at=datetime(2026, 7, 21, tzinfo=timezone.utc))
    eligibility = create_refund_eligibility(db_session, order)
    repo = RefundRepository(db_session)
    assert repo.get_latest_event_for_order(order.order_number, customer.id) is latest
    assert repo.list_events_for_order(order.order_number, customer.id) == [latest] + [
        event for event in refund.events if event is not latest
    ]
    assert repo.count_events_for_order(order.order_number, customer.id) == 2
    assert repo.get_eligibility_for_order(order.order_number, customer.id) is eligibility
