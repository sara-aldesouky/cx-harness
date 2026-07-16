"""EvaluationRepository integration tests."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.database.repositories import EvaluationRepository, RepositoryValidationError
from tests.models.factories import (
    create_conversation,
    create_customer,
    create_evaluation,
    create_model_run,
)
from tests.repositories.conftest import table_counts


def create_evaluation_set(session):
    customer = create_customer(session)
    conversation = create_conversation(session, customer)
    first_run = create_model_run(session, conversation)
    second_run = create_model_run(
        session,
        conversation,
        provider="qwen",
        model_name="qwen-test",
    )
    low = create_evaluation(
        session,
        first_run,
        evaluator_type="automatic",
        evaluator_name="rule_based_v1",
        overall_score=Decimal("2.00"),
        passed=False,
    )
    exact = create_evaluation(
        session,
        first_run,
        evaluator_type="human",
        evaluator_name="manager_review",
        overall_score=Decimal("4.00"),
        passed=True,
    )
    high = create_evaluation(
        session,
        second_run,
        evaluator_type="llm_judge",
        evaluator_name="gemini_judge",
        overall_score=Decimal("5.00"),
        passed=True,
    )
    unscored = create_evaluation(
        session,
        second_run,
        evaluator_type="automatic",
        evaluator_name="language_rules",
        intent_score=None,
        tool_score=None,
        overall_score=None,
        passed=False,
        notes="Manual follow-up required",
        details_json=None,
    )
    low.evaluated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    exact.evaluated_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    high.evaluated_at = datetime(2025, 1, 3, tzinfo=timezone.utc)
    unscored.evaluated_at = datetime(2025, 1, 4, tzinfo=timezone.utc)
    session.flush()
    return first_run, second_run, low, exact, high, unscored


def test_list_count_lookup_and_missing_evaluation(repository_session):
    _, _, low, exact, high, unscored = create_evaluation_set(repository_session)
    repository = EvaluationRepository(repository_session)

    assert repository.count_evaluations() == 4
    assert repository.list_evaluations() == [unscored, high, exact, low]
    assert repository.get_by_id(exact.id) == exact
    assert repository.get_by_id(uuid4()) is None


def test_model_run_and_evaluator_filters(repository_session):
    first_run, _, low, exact, high, unscored = create_evaluation_set(
        repository_session
    )
    repository = EvaluationRepository(repository_session)

    assert repository.list_by_model_run(first_run.id) == [exact, low]
    assert repository.list_by_evaluator_type("automatic") == [unscored, low]
    assert repository.list_by_evaluator_name("manager_review") == [exact]
    assert high not in repository.list_by_model_run(first_run.id)


def test_passed_and_failed_filters(repository_session):
    _, _, low, exact, high, unscored = create_evaluation_set(repository_session)
    repository = EvaluationRepository(repository_session)

    assert repository.list_passed() == [high, exact]
    assert repository.list_failed() == [unscored, low]


def test_minimum_score_filter_is_inclusive_and_excludes_null(
    repository_session,
):
    _, _, low, exact, high, unscored = create_evaluation_set(repository_session)
    repository = EvaluationRepository(repository_session)

    assert repository.list_by_minimum_overall_score(Decimal("4.00")) == [
        high,
        exact,
    ]
    assert low not in repository.list_by_minimum_overall_score(Decimal("4.00"))
    assert unscored not in repository.list_by_minimum_overall_score(
        Decimal("0")
    )


def test_score_range_boundaries_exact_match_and_empty_result(repository_session):
    _, _, low, exact, high, unscored = create_evaluation_set(repository_session)
    repository = EvaluationRepository(repository_session)

    assert repository.list_by_score_range(Decimal("2"), Decimal("4")) == [
        exact,
        low,
    ]
    assert repository.list_by_score_range(Decimal("4"), Decimal("4")) == [exact]
    assert repository.list_by_score_range(Decimal("4.5"), Decimal("4.9")) == []
    assert unscored not in repository.list_by_score_range(
        Decimal("0"), Decimal("5")
    )


def test_combined_evaluation_filters(repository_session):
    first_run, _, low, exact, high, _ = create_evaluation_set(repository_session)
    repository = EvaluationRepository(repository_session)

    assert repository.list_evaluations(
        model_run_id=first_run.id,
        evaluator_type="human",
    ) == [exact]
    assert repository.list_evaluations(
        evaluator_type="llm_judge",
        passed=True,
    ) == [high]
    assert repository.list_evaluations(
        evaluator_name="manager_review",
        minimum_overall_score=Decimal("4"),
        maximum_overall_score=Decimal("4"),
    ) == [exact]
    assert repository.list_evaluations(
        model_run_id=first_run.id,
        passed=False,
        minimum_overall_score=Decimal("2"),
    ) == [low]


def test_evaluation_pagination_and_deterministic_order(repository_session):
    _, _, low, exact, high, unscored = create_evaluation_set(repository_session)
    repository = EvaluationRepository(repository_session)

    first_page = repository.list_evaluations(limit=2)
    second_page = repository.list_evaluations(limit=2, offset=2)

    assert first_page + second_page == [unscored, high, exact, low]
    assert set(first_page).isdisjoint(second_page)
    assert repository.list_evaluations(limit=2) == first_page


def test_latest_and_earliest_evaluations(repository_session):
    first_run, second_run, low, exact, high, unscored = create_evaluation_set(
        repository_session
    )
    repository = EvaluationRepository(repository_session)

    assert repository.latest_evaluation() == unscored
    assert repository.earliest_evaluation() == low
    assert repository.latest_evaluation(first_run.id) == exact
    assert repository.earliest_evaluation(first_run.id) == low
    assert repository.latest_evaluation(second_run.id) == unscored
    assert repository.earliest_evaluation(uuid4()) is None
    assert high != unscored


@pytest.mark.parametrize(
    "method",
    ["list_by_evaluator_type", "list_evaluations"],
)
def test_evaluation_repository_rejects_invalid_evaluator_type(
    repository_session, method
):
    repository = EvaluationRepository(repository_session)

    with pytest.raises(RepositoryValidationError):
        if method == "list_evaluations":
            repository.list_evaluations(evaluator_type="external")
        else:
            repository.list_by_evaluator_type("external")


@pytest.mark.parametrize(
    "limit,offset",
    [(0, 0), (-1, 0), (101, 0), (1, -1), ("10", 0), (1, None)],
)
def test_evaluation_repository_rejects_invalid_pagination(
    repository_session, limit, offset
):
    with pytest.raises(RepositoryValidationError):
        EvaluationRepository(repository_session).list_evaluations(
            limit=limit, offset=offset
        )


@pytest.mark.parametrize(
    "score",
    [
        "not-a-number",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("-0.01"),
        Decimal("5.01"),
        True,
    ],
)
def test_evaluation_repository_rejects_invalid_minimum_score(
    repository_session, score
):
    with pytest.raises(RepositoryValidationError):
        EvaluationRepository(
            repository_session
        ).list_by_minimum_overall_score(score)


def test_evaluation_repository_rejects_reversed_score_range(repository_session):
    with pytest.raises(RepositoryValidationError):
        EvaluationRepository(repository_session).list_by_score_range(
            Decimal("4"), Decimal("3")
        )


@pytest.mark.parametrize(
    "minimum,maximum",
    [
        (Decimal("-0.01"), Decimal("4")),
        (Decimal("1"), Decimal("5.01")),
        (Decimal("NaN"), Decimal("5")),
        (Decimal("0"), "invalid"),
    ],
)
def test_combined_filters_reject_invalid_score_boundaries(
    repository_session, minimum, maximum
):
    with pytest.raises(RepositoryValidationError):
        EvaluationRepository(repository_session).list_evaluations(
            minimum_overall_score=minimum,
            maximum_overall_score=maximum,
        )


def test_evaluation_eager_loads_model_run_in_one_query(
    repository_session, count_queries
):
    _, _, _, exact, _, _ = create_evaluation_set(repository_session)
    evaluation_id = exact.id
    model_run_id = exact.model_run_id
    repository_session.expire_all()

    with count_queries() as statements:
        loaded = EvaluationRepository(repository_session).get_with_model_run(
            evaluation_id
        )
        assert loaded.model_run.id == model_run_id
        assert loaded.model_run.model_name

    assert len(statements) == 1


def test_evaluation_repository_methods_are_read_only(repository_session):
    first_run, _, low, exact, _, _ = create_evaluation_set(repository_session)
    repository = EvaluationRepository(repository_session)
    before = table_counts(repository_session)

    repository.list_evaluations()
    repository.count_evaluations()
    repository.get_by_id(exact.id)
    repository.get_with_model_run(exact.id)
    repository.list_by_model_run(first_run.id)
    repository.list_by_evaluator_type("automatic")
    repository.list_by_evaluator_name("manager_review")
    repository.list_passed()
    repository.list_failed()
    repository.list_by_minimum_overall_score(Decimal("2"))
    repository.list_by_score_range(Decimal("2"), Decimal("5"))
    repository.latest_evaluation()
    repository.earliest_evaluation()
    repository.get_by_id(low.id)

    assert table_counts(repository_session) == before
