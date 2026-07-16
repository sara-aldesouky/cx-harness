"""ToolCallRepository integration tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.database.repositories import RepositoryValidationError, ToolCallRepository
from tests.models.factories import (
    create_conversation,
    create_customer,
    create_model_run,
    create_tool_call,
)
from tests.repositories.conftest import table_counts


def create_tool_call_set(session):
    customer = create_customer(session)
    conversation = create_conversation(session, customer)
    first_run = create_model_run(session, conversation)
    second_run = create_model_run(
        session,
        conversation,
        provider="qwen",
        model_name="qwen-test",
    )
    requested = create_tool_call(
        session,
        first_run,
        tool_name="cancel_order",
        status="requested",
        output_json=None,
        success=False,
        latency_ms=None,
    )
    completed = create_tool_call(
        session,
        first_run,
        tool_name="get_order_status",
        status="completed",
        success=True,
    )
    failed = create_tool_call(
        session,
        second_run,
        tool_name="request_refund",
        status="failed",
        output_json=None,
        success=False,
        error_message="Synthetic failure",
    )
    requested.requested_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    completed.requested_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    failed.requested_at = datetime(2025, 1, 3, tzinfo=timezone.utc)
    session.flush()
    return first_run, second_run, requested, completed, failed


def test_list_count_lookup_and_missing_tool_call(repository_session):
    _, _, requested, completed, failed = create_tool_call_set(repository_session)
    repository = ToolCallRepository(repository_session)

    assert repository.count_tool_calls() == 3
    assert repository.list_tool_calls() == [failed, completed, requested]
    assert repository.get_by_id(completed.id) == completed
    assert repository.get_by_id(uuid4()) is None


def test_tool_call_filters(repository_session):
    first_run, _, requested, completed, failed = create_tool_call_set(
        repository_session
    )
    repository = ToolCallRepository(repository_session)

    assert repository.list_by_model_run(first_run.id) == [completed, requested]
    assert repository.list_by_status("failed") == [failed]
    assert repository.list_by_tool_name("get_order_status") == [completed]
    assert repository.list_by_tool_name("unknown_tool") == []


def test_combined_tool_call_filters(repository_session):
    first_run, _, requested, completed, _ = create_tool_call_set(
        repository_session
    )
    repository = ToolCallRepository(repository_session)

    assert repository.list_tool_calls(
        model_run_id=first_run.id,
        status="completed",
        tool_name="get_order_status",
        success=True,
    ) == [completed]
    assert repository.list_tool_calls(
        model_run_id=first_run.id,
        success=False,
    ) == [requested]


def test_success_and_status_groups(repository_session):
    _, _, requested, completed, failed = create_tool_call_set(repository_session)
    repository = ToolCallRepository(repository_session)

    assert repository.list_successful() == [completed]
    assert repository.list_failed() == [failed]
    assert repository.list_completed() == [completed]
    assert repository.list_requested() == [requested]


def test_latest_and_earliest_tool_calls(repository_session):
    first_run, second_run, requested, completed, failed = create_tool_call_set(
        repository_session
    )
    repository = ToolCallRepository(repository_session)

    assert repository.latest_tool_call() == failed
    assert repository.earliest_tool_call() == requested
    assert repository.latest_tool_call(first_run.id) == completed
    assert repository.earliest_tool_call(first_run.id) == requested
    assert repository.latest_tool_call(second_run.id) == failed
    assert repository.earliest_tool_call(uuid4()) is None


def test_tool_call_pagination_is_deterministic(repository_session):
    _, _, requested, completed, failed = create_tool_call_set(repository_session)
    repository = ToolCallRepository(repository_session)

    first_page = repository.list_tool_calls(limit=2)
    second_page = repository.list_tool_calls(limit=2, offset=2)

    assert first_page + second_page == [failed, completed, requested]
    assert repository.list_tool_calls(limit=2) == first_page


@pytest.mark.parametrize(
    "method",
    ["list_by_status", "list_tool_calls"],
)
def test_tool_call_repository_rejects_invalid_status(repository_session, method):
    repository = ToolCallRepository(repository_session)

    with pytest.raises(RepositoryValidationError):
        if method == "list_tool_calls":
            repository.list_tool_calls(status="unknown")
        else:
            repository.list_by_status("unknown")


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (101, 0), (-1, 0), (1, -1), (True, 0), (1, None)],
)
def test_tool_call_repository_rejects_invalid_pagination(
    repository_session, limit, offset
):
    with pytest.raises(RepositoryValidationError):
        ToolCallRepository(repository_session).list_tool_calls(
            limit=limit, offset=offset
        )


def test_tool_call_eager_loads_model_run_in_one_query(
    repository_session, count_queries
):
    _, _, _, completed, _ = create_tool_call_set(repository_session)
    tool_call_id = completed.id
    model_run_id = completed.model_run_id
    repository_session.expire_all()

    with count_queries() as statements:
        loaded = ToolCallRepository(repository_session).get_with_model_run(
            tool_call_id
        )
        assert loaded.model_run.id == model_run_id
        assert loaded.model_run.model_name

    assert len(statements) == 1


def test_tool_call_repository_methods_are_read_only(repository_session):
    first_run, _, requested, completed, _ = create_tool_call_set(repository_session)
    repository = ToolCallRepository(repository_session)
    before = table_counts(repository_session)

    repository.list_tool_calls()
    repository.count_tool_calls()
    repository.get_by_id(completed.id)
    repository.get_with_model_run(completed.id)
    repository.list_by_model_run(first_run.id)
    repository.list_by_status("completed")
    repository.list_by_tool_name("get_order_status")
    repository.list_successful()
    repository.list_failed()
    repository.list_completed()
    repository.list_requested()
    repository.latest_tool_call()
    repository.earliest_tool_call()
    repository.get_by_id(requested.id)

    assert table_counts(repository_session) == before
