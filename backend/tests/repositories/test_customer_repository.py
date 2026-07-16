"""CustomerRepository integration tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.database.repositories import CustomerRepository, RepositoryValidationError
from tests.models.factories import create_customer, create_order
from tests.repositories.conftest import table_counts


def test_list_and_count_customers(repository_session):
    first = create_customer(
        repository_session, first_name="Amy", last_name="Alpha"
    )
    second = create_customer(
        repository_session, first_name="Zoe", last_name="Zulu"
    )
    repository = CustomerRepository(repository_session)

    assert repository.count() == 2
    assert repository.list_customers() == [first, second]


def test_customer_lookups_and_missing_result(repository_session):
    customer = create_customer(repository_session)
    repository = CustomerRepository(repository_session)

    assert repository.get_by_id(customer.id) == customer
    assert repository.get_by_email(customer.email) == customer
    assert repository.get_by_phone(customer.phone) == customer
    assert repository.get_by_id(uuid4()) is None
    assert repository.get_by_email("missing@example.test") is None
    assert repository.get_by_phone("+201000000000") is None


def test_list_customer_orders_filters_and_orders_deterministically(
    repository_session,
):
    customer = create_customer(repository_session)
    other_customer = create_customer(repository_session)
    older = create_order(repository_session, customer, order_number="ORDER-B")
    newer = create_order(repository_session, customer, order_number="ORDER-A")
    create_order(repository_session, other_customer)
    older.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    newer.created_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    repository_session.flush()

    orders = CustomerRepository(repository_session).list_orders(customer.id)

    assert orders == [newer, older]


def test_customer_pagination_is_deterministic(repository_session):
    customers = [
        create_customer(
            repository_session, first_name=name, last_name="Same"
        )
        for name in ("Charlie", "Alice", "Bob")
    ]
    expected = sorted(customers, key=lambda value: (value.last_name, value.first_name, value.id))
    repository = CustomerRepository(repository_session)

    first_page = repository.list_customers(limit=2)
    second_page = repository.list_customers(limit=2, offset=2)

    assert first_page + second_page == expected
    assert repository.list_customers(limit=2) == first_page


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (101, 0), (-1, 0), (1, -1), (True, 0), (1, False)],
)
def test_customer_repository_rejects_invalid_pagination(
    repository_session, limit, offset
):
    repository = CustomerRepository(repository_session)

    with pytest.raises(RepositoryValidationError):
        repository.list_customers(limit=limit, offset=offset)


def test_customer_orders_are_eager_loaded_without_n_plus_one(
    repository_session, count_queries
):
    customer = create_customer(repository_session)
    create_order(repository_session, customer)
    create_order(repository_session, customer)
    customer_id = customer.id
    repository_session.expire_all()
    repository = CustomerRepository(repository_session)

    with count_queries() as statements:
        loaded = repository.get_with_orders(customer_id)
        assert len(loaded.orders) == 2
        assert [order.order_number for order in loaded.orders]

    assert len(statements) == 2


def test_customer_repository_methods_are_read_only(repository_session):
    customer = create_customer(repository_session)
    create_order(repository_session, customer)
    repository = CustomerRepository(repository_session)
    before = table_counts(repository_session)

    repository.list_customers()
    repository.count()
    repository.get_by_id(customer.id)
    repository.get_by_email(customer.email)
    repository.get_by_phone(customer.phone)
    repository.list_orders(customer.id)
    repository.get_with_orders(customer.id)

    assert table_counts(repository_session) == before
