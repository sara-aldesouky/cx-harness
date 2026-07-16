"""MessageRepository integration tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.database.repositories import MessageRepository, RepositoryValidationError
from tests.models.factories import (
    create_conversation,
    create_customer,
    create_message,
)
from tests.repositories.conftest import table_counts


def create_message_set(session):
    customer = create_customer(session)
    conversation = create_conversation(session, customer)
    other_conversation = create_conversation(session, customer)
    first = create_message(
        session,
        conversation,
        role="user",
        language="english",
        sequence_number=1,
    )
    second = create_message(
        session,
        conversation,
        role="assistant",
        content="تمام، I will check.",
        language="mixed",
        sequence_number=2,
    )
    third = create_message(
        session,
        conversation,
        role="tool",
        content="Tool result",
        language=None,
        sequence_number=3,
    )
    other = create_message(session, other_conversation, sequence_number=1)
    first.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    second.created_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    third.created_at = datetime(2025, 1, 3, tzinfo=timezone.utc)
    other.created_at = datetime(2025, 1, 4, tzinfo=timezone.utc)
    session.flush()
    return conversation, other_conversation, first, second, third, other


def test_list_count_lookup_and_missing_message(repository_session):
    _, _, first, second, third, other = create_message_set(repository_session)
    repository = MessageRepository(repository_session)

    assert repository.count() == 4
    assert repository.list_messages() == [first, second, third, other]
    assert repository.get_by_id(second.id) == second
    assert repository.get_by_id(uuid4()) is None


def test_message_conversation_role_and_language_filters(repository_session):
    conversation, _, first, second, third, other = create_message_set(
        repository_session
    )
    repository = MessageRepository(repository_session)

    assert repository.list_by_conversation_id(conversation.id) == [
        first,
        second,
        third,
    ]
    assert repository.list_by_role("assistant") == [second]
    assert repository.list_by_language("mixed") == [second]
    assert third.language is None
    assert third in repository.list_by_conversation_id(conversation.id)
    assert third not in repository.list_by_language("unknown")
    assert other not in repository.list_by_conversation_id(conversation.id)


def test_latest_earliest_and_ordered_history(repository_session):
    conversation, _, first, second, third, _ = create_message_set(
        repository_session
    )
    repository = MessageRepository(repository_session)

    assert repository.get_earliest_in_conversation(conversation.id) == first
    assert repository.get_latest_in_conversation(conversation.id) == third
    assert repository.get_conversation_history(conversation.id) == [
        first,
        second,
        third,
    ]
    assert repository.get_latest_in_conversation(uuid4()) is None
    assert repository.get_earliest_in_conversation(uuid4()) is None


def test_message_pagination_is_deterministic(repository_session):
    conversation, _, first, second, third, _ = create_message_set(
        repository_session
    )
    repository = MessageRepository(repository_session)

    first_page = repository.get_conversation_history(conversation.id, limit=2)
    second_page = repository.get_conversation_history(
        conversation.id, limit=2, offset=2
    )

    assert first_page + second_page == [first, second, third]
    assert repository.get_conversation_history(conversation.id, limit=2) == first_page


@pytest.mark.parametrize(
    "method,value",
    [("list_by_role", "agent"), ("list_by_language", "french")],
)
def test_message_repository_rejects_invalid_filters(
    repository_session, method, value
):
    with pytest.raises(RepositoryValidationError):
        getattr(MessageRepository(repository_session), method)(value)


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (101, 0), (-1, 0), (1, -1), ("10", 0), (1, False)],
)
def test_message_repository_rejects_invalid_pagination(
    repository_session, limit, offset
):
    with pytest.raises(RepositoryValidationError):
        MessageRepository(repository_session).list_messages(
            limit=limit, offset=offset
        )


def test_message_repository_methods_are_read_only(repository_session):
    conversation, _, first, _, _, _ = create_message_set(repository_session)
    repository = MessageRepository(repository_session)
    before = table_counts(repository_session)

    repository.list_messages()
    repository.count()
    repository.get_by_id(first.id)
    repository.list_by_conversation_id(conversation.id)
    repository.list_by_role("user")
    repository.list_by_language("english")
    repository.get_latest_in_conversation(conversation.id)
    repository.get_earliest_in_conversation(conversation.id)
    repository.get_conversation_history(conversation.id)

    assert table_counts(repository_session) == before
