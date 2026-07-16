"""ModelRunRepository integration tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.database.repositories import ModelRunRepository, RepositoryValidationError
from tests.models.factories import (
    create_conversation,
    create_customer,
    create_model_run,
)
from tests.repositories.conftest import table_counts


def create_model_run_set(session):
    customer = create_customer(session)
    conversation = create_conversation(session, customer)
    other_conversation = create_conversation(session, customer)
    gemini = create_model_run(
        session,
        conversation,
        provider="gemini",
        model_name="gemini-test",
        status="completed",
        success=True,
    )
    qwen = create_model_run(
        session,
        conversation,
        provider="qwen",
        model_name="qwen-test",
        status="failed",
        success=False,
        error_message="Synthetic failure",
    )
    fanar = create_model_run(
        session,
        other_conversation,
        provider="fanar",
        model_name="fanar-test",
        status="completed",
        success=True,
    )
    gemini.started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    qwen.started_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    fanar.started_at = datetime(2025, 1, 3, tzinfo=timezone.utc)
    session.flush()
    return conversation, other_conversation, gemini, qwen, fanar


def test_list_count_lookup_and_missing_model_run(repository_session):
    _, _, gemini, qwen, fanar = create_model_run_set(repository_session)
    repository = ModelRunRepository(repository_session)

    assert repository.count() == 3
    assert repository.list_model_runs() == [fanar, qwen, gemini]
    assert repository.get_by_id(qwen.id) == qwen
    assert repository.get_by_id(uuid4()) is None


def test_model_run_filters(repository_session):
    conversation, _, gemini, qwen, fanar = create_model_run_set(
        repository_session
    )
    repository = ModelRunRepository(repository_session)

    assert repository.list_by_conversation_id(conversation.id) == [qwen, gemini]
    assert repository.list_by_provider("gemini") == [gemini]
    assert repository.list_by_model("qwen-test") == [qwen]
    assert repository.list_by_status("completed") == [fanar, gemini]


def test_latest_successful_and_failed_model_runs(repository_session):
    conversation, _, gemini, qwen, fanar = create_model_run_set(
        repository_session
    )
    repository = ModelRunRepository(repository_session)

    assert repository.get_latest() == fanar
    assert repository.get_latest(conversation.id) == qwen
    assert repository.get_latest(uuid4()) is None
    assert repository.list_successful() == [fanar, gemini]
    assert repository.list_failed() == [qwen]


def test_model_run_pagination_is_deterministic(repository_session):
    _, _, gemini, qwen, fanar = create_model_run_set(repository_session)
    repository = ModelRunRepository(repository_session)

    first_page = repository.list_model_runs(limit=2)
    second_page = repository.list_model_runs(limit=2, offset=2)

    assert first_page + second_page == [fanar, qwen, gemini]
    assert repository.list_model_runs(limit=2) == first_page


@pytest.mark.parametrize(
    "method,value",
    [("list_by_provider", "openai"), ("list_by_status", "timed_out")],
)
def test_model_run_repository_rejects_invalid_filters(
    repository_session, method, value
):
    with pytest.raises(RepositoryValidationError):
        getattr(ModelRunRepository(repository_session), method)(value)


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (101, 0), (-1, 0), (1, -1), (None, 0), (1, True)],
)
def test_model_run_repository_rejects_invalid_pagination(
    repository_session, limit, offset
):
    with pytest.raises(RepositoryValidationError):
        ModelRunRepository(repository_session).list_model_runs(
            limit=limit, offset=offset
        )


def test_model_run_repository_methods_are_read_only(repository_session):
    conversation, _, gemini, _, _ = create_model_run_set(repository_session)
    repository = ModelRunRepository(repository_session)
    before = table_counts(repository_session)

    repository.list_model_runs()
    repository.count()
    repository.get_by_id(gemini.id)
    repository.list_by_conversation_id(conversation.id)
    repository.list_by_provider("gemini")
    repository.list_by_model("gemini-test")
    repository.list_by_status("completed")
    repository.get_latest()
    repository.list_successful()
    repository.list_failed()

    assert table_counts(repository_session) == before
