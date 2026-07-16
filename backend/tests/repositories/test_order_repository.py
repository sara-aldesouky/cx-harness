"""OrderRepository integration tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.database.repositories import OrderRepository, RepositoryValidationError
from tests.models.factories import create_customer, create_order, create_order_item
from tests.repositories.conftest import table_counts


def create_order_set(session):
    customer = create_customer(session)
    other_customer = create_customer(session)
    pending = create_order(
        session,
        customer,
        order_number="ORDER-PENDING",
        status="pending",
        payment_status="pending",
    )
    delivered = create_order(
        session,
        customer,
        order_number="ORDER-DELIVERED",
        status="delivered",
        payment_status="paid",
    )
    other = create_order(
        session,
        other_customer,
        order_number="ORDER-OTHER",
        status="cancelled",
        payment_status="refunded",
    )
    pending.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    delivered.created_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    other.created_at = datetime(2025, 1, 3, tzinfo=timezone.utc)
    session.flush()
    return customer, other_customer, pending, delivered, other


def test_list_count_and_order_lookups(repository_session):
    _, _, pending, delivered, other = create_order_set(repository_session)
    repository = OrderRepository(repository_session)

    assert repository.count() == 3
    assert repository.list_orders() == [other, delivered, pending]
    assert repository.get_by_id(delivered.id) == delivered
    assert repository.get_by_order_number(pending.order_number) == pending
    assert repository.get_by_id(uuid4()) is None
    assert repository.get_by_order_number("MISSING") is None


def test_order_filters(repository_session):
    customer, _, pending, delivered, other = create_order_set(repository_session)
    repository = OrderRepository(repository_session)

    assert repository.list_by_customer_id(customer.id) == [delivered, pending]
    assert repository.list_by_status("pending") == [pending]
    assert repository.list_by_payment_status("paid") == [delivered]
    assert other not in repository.list_by_customer_id(customer.id)
    assert repository.list_orders(
        customer_id=customer.id,
        status="delivered",
        payment_status="paid",
    ) == [delivered]
    assert repository.count_orders(
        customer_id=customer.id,
        status="delivered",
        payment_status="paid",
    ) == 1


def test_order_pagination_is_deterministic(repository_session):
    _, _, pending, delivered, other = create_order_set(repository_session)
    repository = OrderRepository(repository_session)

    first_page = repository.list_orders(limit=2)
    second_page = repository.list_orders(limit=2, offset=2)

    assert first_page + second_page == [other, delivered, pending]
    assert repository.list_orders(limit=2) == first_page


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (101, 0), (-1, 0), (1, -1), ("10", 0), (1, None)],
)
def test_order_repository_rejects_invalid_pagination(
    repository_session, limit, offset
):
    with pytest.raises(RepositoryValidationError):
        OrderRepository(repository_session).list_orders(limit=limit, offset=offset)


@pytest.mark.parametrize(
    "method,value",
    [("list_by_status", "unknown"), ("list_by_payment_status", "unknown")],
)
def test_order_repository_rejects_unsupported_filters(
    repository_session, method, value
):
    repository = OrderRepository(repository_session)

    with pytest.raises(RepositoryValidationError):
        getattr(repository, method)(value)


def test_order_customer_and_items_are_eager_loaded_without_n_plus_one(
    repository_session, count_queries
):
    customer = create_customer(repository_session)
    order = create_order(repository_session, customer)
    create_order_item(repository_session, order, product_name="First")
    create_order_item(repository_session, order, product_name="Second")
    order_id = order.id
    customer_email = customer.email
    repository_session.expire_all()
    repository = OrderRepository(repository_session)

    with count_queries() as statements:
        loaded = repository.get_with_customer_and_items(order_id)
        assert loaded.customer.email == customer_email
        assert len(loaded.items) == 2
        assert [item.product_name for item in loaded.items]
        assert loaded.conversations == []

    assert len(statements) == 3


def test_order_repository_methods_are_read_only(repository_session):
    customer, _, pending, _, _ = create_order_set(repository_session)
    create_order_item(repository_session, pending)
    repository = OrderRepository(repository_session)
    before = table_counts(repository_session)

    repository.list_orders()
    repository.count()
    repository.get_by_id(pending.id)
    repository.get_by_order_number(pending.order_number)
    repository.list_by_customer_id(customer.id)
    repository.list_by_status("pending")
    repository.list_by_payment_status("pending")
    repository.get_with_customer_and_items(pending.id)

    assert table_counts(repository_session) == before
