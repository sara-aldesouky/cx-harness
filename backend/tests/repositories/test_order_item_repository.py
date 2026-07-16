"""OrderItemRepository integration tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.database.repositories import OrderItemRepository, RepositoryValidationError
from tests.models.factories import create_customer, create_order, create_order_item
from tests.repositories.conftest import table_counts


def create_item_set(session):
    customer = create_customer(session)
    first_order = create_order(session, customer)
    second_order = create_order(session, customer)
    first = create_order_item(
        session, first_order, product_name="First", item_status="included"
    )
    second = create_order_item(
        session, first_order, product_name="Second", item_status="missing"
    )
    third = create_order_item(
        session, second_order, product_name="Third", item_status="refunded"
    )
    first.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    second.created_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    third.created_at = datetime(2025, 1, 3, tzinfo=timezone.utc)
    session.flush()
    return first_order, second_order, first, second, third


def test_list_count_and_item_lookups(repository_session):
    _, _, first, second, third = create_item_set(repository_session)
    repository = OrderItemRepository(repository_session)

    assert repository.count() == 3
    assert repository.list_items() == [first, second, third]
    assert repository.get_by_id(second.id) == second
    assert repository.get_by_id(uuid4()) is None


def test_order_item_filters(repository_session):
    first_order, _, first, second, third = create_item_set(repository_session)
    repository = OrderItemRepository(repository_session)

    assert repository.list_by_order_id(first_order.id) == [first, second]
    assert repository.list_by_status("missing") == [second]
    assert third not in repository.list_by_order_id(first_order.id)


def test_order_item_pagination_is_deterministic(repository_session):
    _, _, first, second, third = create_item_set(repository_session)
    repository = OrderItemRepository(repository_session)

    first_page = repository.list_items(limit=2)
    second_page = repository.list_items(limit=2, offset=2)

    assert first_page + second_page == [first, second, third]
    assert repository.list_items(limit=2) == first_page


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (101, 0), (-1, 0), (1, -1), (1.5, 0), (1, "0")],
)
def test_order_item_repository_rejects_invalid_pagination(
    repository_session, limit, offset
):
    with pytest.raises(RepositoryValidationError):
        OrderItemRepository(repository_session).list_items(
            limit=limit, offset=offset
        )


def test_order_item_repository_rejects_unsupported_status(repository_session):
    with pytest.raises(RepositoryValidationError):
        OrderItemRepository(repository_session).list_by_status("unknown")


def test_order_item_repository_methods_are_read_only(repository_session):
    first_order, _, first, _, _ = create_item_set(repository_session)
    repository = OrderItemRepository(repository_session)
    before = table_counts(repository_session)

    repository.list_items()
    repository.count()
    repository.get_by_id(first.id)
    repository.list_by_order_id(first_order.id)
    repository.list_by_status("included")

    assert table_counts(repository_session) == before
