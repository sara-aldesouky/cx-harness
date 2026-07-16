"""ConversationRepository integration tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.database.repositories import (
    ConversationRepository,
    RepositoryValidationError,
)
from tests.models.factories import (
    create_conversation,
    create_customer,
    create_message,
    create_model_run,
    create_order,
)
from tests.repositories.conftest import table_counts


def create_conversation_set(session):
    customer = create_customer(session)
    other_customer = create_customer(session)
    order = create_order(session, customer)
    active = create_conversation(
        session,
        customer,
        order,
        status="open",
        channel="web",
    )
    waiting = create_conversation(
        session,
        customer,
        status="waiting_for_agent",
        channel="whatsapp",
    )
    closed = create_conversation(
        session,
        other_customer,
        status="closed",
        channel="mobile",
    )
    active.started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    waiting.started_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    closed.started_at = datetime(2025, 1, 3, tzinfo=timezone.utc)
    session.flush()
    return customer, other_customer, order, active, waiting, closed


def test_list_count_lookup_and_missing_conversation(repository_session):
    _, _, _, active, waiting, closed = create_conversation_set(repository_session)
    repository = ConversationRepository(repository_session)

    assert repository.count() == 3
    assert repository.list_conversations() == [closed, waiting, active]
    assert repository.get_by_id(waiting.id) == waiting
    assert repository.get_by_id(uuid4()) is None


def test_conversation_filters(repository_session):
    customer, _, order, active, waiting, closed = create_conversation_set(
        repository_session
    )
    repository = ConversationRepository(repository_session)

    assert repository.list_by_customer_id(customer.id) == [waiting, active]
    assert repository.list_by_related_order_id(order.id) == [active]
    assert repository.list_by_status("open") == [active]
    assert repository.list_by_channel("whatsapp") == [waiting]
    assert closed not in repository.list_by_customer_id(customer.id)


def test_active_and_closed_conversation_groups(repository_session):
    customer = create_customer(repository_session)
    active = [
        create_conversation(
            repository_session, customer, status=status, channel="web"
        )
        for status in (
            "open",
            "waiting_for_customer",
            "waiting_for_agent",
            "escalated",
        )
    ]
    closed = [
        create_conversation(
            repository_session, customer, status=status, channel="web"
        )
        for status in ("resolved", "closed")
    ]
    repository = ConversationRepository(repository_session)

    assert set(repository.list_active()) == set(active)
    assert set(repository.list_closed()) == set(closed)


def test_conversation_pagination_and_deterministic_order(repository_session):
    _, _, _, active, waiting, closed = create_conversation_set(repository_session)
    repository = ConversationRepository(repository_session)

    first_page = repository.list_conversations(limit=2)
    second_page = repository.list_conversations(limit=2, offset=2)

    assert first_page + second_page == [closed, waiting, active]
    assert repository.list_conversations(limit=2) == first_page


@pytest.mark.parametrize(
    "method,value",
    [("list_by_status", "invalid"), ("list_by_channel", "email")],
)
def test_conversation_repository_rejects_invalid_filters(
    repository_session, method, value
):
    with pytest.raises(RepositoryValidationError):
        getattr(ConversationRepository(repository_session), method)(value)


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (101, 0), (-1, 0), (1, -1), (True, 0), (1, None)],
)
def test_conversation_repository_rejects_invalid_pagination(
    repository_session, limit, offset
):
    with pytest.raises(RepositoryValidationError):
        ConversationRepository(repository_session).list_conversations(
            limit=limit, offset=offset
        )


def test_conversation_details_are_eager_loaded_without_n_plus_one(
    repository_session, count_queries
):
    customer = create_customer(repository_session)
    order = create_order(repository_session, customer)
    conversation = create_conversation(repository_session, customer, order)
    create_message(repository_session, conversation, sequence_number=1)
    create_message(
        repository_session,
        conversation,
        role="assistant",
        content="Response",
        sequence_number=2,
    )
    create_model_run(repository_session, conversation)
    create_model_run(
        repository_session,
        conversation,
        provider="qwen",
        model_name="qwen-test",
    )
    conversation_id = conversation.id
    customer_id = customer.id
    order_id = order.id
    repository_session.expire_all()

    with count_queries() as statements:
        loaded = ConversationRepository(repository_session).get_with_details(
            conversation_id
        )
        assert loaded.customer.id == customer_id
        assert loaded.related_order.id == order_id
        assert len(loaded.messages) == 2
        assert len(loaded.model_runs) == 2

    assert len(statements) == 3


def test_conversation_repository_methods_are_read_only(repository_session):
    customer, _, order, active, _, _ = create_conversation_set(repository_session)
    repository = ConversationRepository(repository_session)
    before = table_counts(repository_session)

    repository.list_conversations()
    repository.count()
    repository.get_by_id(active.id)
    repository.list_by_customer_id(customer.id)
    repository.list_by_related_order_id(order.id)
    repository.list_by_status("open")
    repository.list_by_channel("web")
    repository.list_active()
    repository.list_closed()
    repository.get_with_details(active.id)

    assert table_counts(repository_session) == before
