from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.benchmark_analytics.contracts import (
    BenchmarkRunDefinition, BenchmarkSuiteDefinition, ConversationResultRecord,
    DeploymentMode, EvaluationMethod, FailureCategory, FailureEventRecord,
    FailureSeverity, FinalOutcome, MetricResultRecord, ModelConfigurationSnapshot,
    PricingSnapshot, ProviderTurnRecord, ProviderType, ResponsibilityLayer,
    RunStatus, SuiteStatus, ToolExecutionRecord,
)
from app.benchmark_analytics.repositories import (
    BenchmarkConversationResultRepository, BenchmarkFailureRepository,
    BenchmarkMetricRepository, BenchmarkProviderTurnRepository,
    BenchmarkRunRepository, BenchmarkSuiteRepository,
    BenchmarkToolExecutionRepository,
)
from app.database.models import BenchmarkRun, BenchmarkSuite

pytestmark = pytest.mark.integration
NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def suite(key="suite"):
    return BenchmarkSuiteDefinition(suite_key=key, name="Suite", description="Description", version="1", test_case_count=2, content_hash="sha256:test", created_at=NOW, updated_at=NOW)


def run(suite_id, key="run", model="qwen3:8b"):
    return BenchmarkRunDefinition(run_key=key, benchmark_suite_id=suite_id, model_name=model, provider_name="ollama", provider_type=ProviderType.LOCAL_RUNTIME, deployment_mode=DeploymentMode.LOCAL, configuration_snapshot=ModelConfigurationSnapshot(temperature=Decimal("0.1"), context_window_limit=8192), pricing_snapshot=PricingSnapshot(hardware_hourly_cost=Decimal("2.00")), created_at=NOW, updated_at=NOW)


def conversation(run_id, key="TC-001", outcome=FinalOutcome.PASSED, language="ar-EG", category="orders"):
    passed = outcome is FinalOutcome.PASSED
    return ConversationResultRecord(benchmark_run_id=run_id, test_case_key=key, language=language, category=category, expected_intent="track", actual_intent="track", final_outcome=outcome, passed=passed, failure_category=None if passed else FailureCategory.BUSINESS_DATA, provider_turn_count=2, customer_turn_count=2, tool_execution_count=1, successful_tool_execution_count=1 if passed else 0, failed_tool_execution_count=0 if passed else 1, input_tokens=10, output_tokens=4, total_tokens=14, total_latency_ms=Decimal("30.5"), started_at=NOW, completed_at=NOW+timedelta(seconds=1), created_at=NOW)


@pytest.fixture
def analytics(db_session):
    suites = BenchmarkSuiteRepository(db_session); created_suite = suites.create(suite())
    runs = BenchmarkRunRepository(db_session); created_run = runs.create(run(created_suite.id))
    conversations = BenchmarkConversationResultRepository(db_session)
    return db_session, suites, runs, conversations, created_suite, created_run


def test_suite_lookup_listing_freeze_and_archive(analytics):
    _, suites, _, _, created, _ = analytics
    assert suites.get_by_id(created.id) == created
    assert suites.get_by_key_version("SUITE", "1") == created
    assert suites.list() == (created,)
    assert suites.freeze(created.id).status is SuiteStatus.FROZEN
    assert suites.archive(created.id).status is SuiteStatus.ARCHIVED


def test_suite_key_version_is_unique(db_session):
    repository = BenchmarkSuiteRepository(db_session); repository.create(suite())
    with pytest.raises(IntegrityError): repository.create(suite())


def test_suite_deletion_is_restricted_when_run_exists(analytics):
    db, suites, _, _, created, _ = analytics
    with pytest.raises(IntegrityError): suites.delete(created.id)
    db.rollback()


def test_run_lifecycle_and_lookup(analytics):
    _, _, runs, _, _, created = analytics
    running = runs.mark_running(created.id, NOW+timedelta(seconds=1)); assert running.status is RunStatus.RUNNING
    completed = runs.mark_completed(created.id, NOW+timedelta(seconds=2)); assert completed.status is RunStatus.COMPLETED
    assert runs.get_by_run_key("run") == completed
    with pytest.raises(ValueError): runs.mark_failed(created.id)


def test_run_filtering_by_suite_and_model(analytics):
    _, _, runs, _, suite_record, created = analytics
    assert runs.list_by_suite(suite_record.id) == (created,)
    assert runs.list_by_model("qwen3:8b") == (created,)


def test_conversation_insert_filter_and_counts(analytics):
    _, _, _, repository, _, run_record = analytics
    one, two = repository.bulk_insert((conversation(run_record.id), conversation(run_record.id, "TC-002", FinalOutcome.FAILED, "en", "payments")))
    assert repository.get_by_run_case(run_record.id, "TC-001") == one
    assert repository.list_by_run(run_record.id) == (one, two)
    assert repository.filter_by_language(run_record.id, "en") == (two,)
    assert repository.filter_by_category(run_record.id, "orders") == (one,)
    assert repository.filter_by_result(run_record.id, FinalOutcome.FAILED) == (two,)
    assert repository.count_by_status(run_record.id) == {"failed": 1, "passed": 1}


def test_duplicate_test_case_per_run_is_rejected(analytics):
    _, _, _, repository, _, run_record = analytics
    repository.insert(conversation(run_record.id))
    with pytest.raises(IntegrityError): repository.insert(conversation(run_record.id))


def test_provider_turns_are_deterministically_ordered(analytics):
    db, _, _, conversations, _, run_record = analytics; result = conversations.insert(conversation(run_record.id))
    repo = BenchmarkProviderTurnRepository(db)
    repo.bulk_insert((ProviderTurnRecord(conversation_result_id=result.id, turn_number=2, finish_reason="stop", input_tokens=2, output_tokens=1, total_tokens=3, created_at=NOW), ProviderTurnRecord(conversation_result_id=result.id, turn_number=1, finish_reason="tool", input_tokens=1, output_tokens=1, total_tokens=2, created_at=NOW)))
    assert [item.turn_number for item in repo.list_in_order(result.id)] == [1, 2]


def test_tool_order_and_aggregates(analytics):
    db, _, _, conversations, _, run_record = analytics; result = conversations.insert(conversation(run_record.id)); repo = BenchmarkToolExecutionRepository(db)
    repo.bulk_insert((ToolExecutionRecord(conversation_result_id=result.id, execution_order=2, tool_name="get_payment_status", selection_correct=False, arguments_valid=True, authorization_passed=True, execution_successful=False, business_failure=True, failure_code="payment_not_found", created_at=NOW), ToolExecutionRecord(conversation_result_id=result.id, execution_order=1, tool_name="list_current_orders", selection_correct=True, arguments_valid=True, authorization_passed=True, execution_successful=True, created_at=NOW)))
    assert [item.execution_order for item in repo.list_by_conversation(result.id)] == [1, 2]
    assert repo.aggregate_by_tool_name(run_record.id) == {"get_payment_status": 1, "list_current_orders": 1}
    assert repo.aggregate_success_failure(run_record.id) == {"failed": 1, "successful": 1}


def test_metric_versions_and_aggregates(analytics):
    db, _, _, conversations, _, run_record = analytics; result = conversations.insert(conversation(run_record.id)); repo = BenchmarkMetricRepository(db)
    repo.bulk_insert((MetricResultRecord(conversation_result_id=result.id, metric_key="grounding", metric_version="1", value_boolean=True, normalized_score=Decimal("1"), evaluation_method=EvaluationMethod.DETERMINISTIC_RULE, evaluator_name="rules", evaluator_version="1", created_at=NOW), MetricResultRecord(conversation_result_id=result.id, metric_key="grounding", metric_version="2", value_numeric=Decimal("0.5"), normalized_score=Decimal("0.5"), evaluation_method=EvaluationMethod.HUMAN_REVIEW, evaluator_name="human", evaluator_version="1", created_at=NOW)))
    assert [item.metric_version for item in repo.list_by_conversation(result.id)] == ["1", "2"]
    assert repo.aggregate_by_metric_key(result.id)["grounding"] == Decimal("0.75")
    assert repo.aggregate_by_model_run(run_record.id)["grounding"] == Decimal("0.75")


def test_duplicate_metric_definition_is_rejected(analytics):
    db, _, _, conversations, _, run_record = analytics; result = conversations.insert(conversation(run_record.id)); repo = BenchmarkMetricRepository(db)
    metric = MetricResultRecord(conversation_result_id=result.id, metric_key="grounding", metric_version="1", value_boolean=True, evaluation_method=EvaluationMethod.DETERMINISTIC_RULE, evaluator_name="rules", evaluator_version="1", created_at=NOW)
    repo.insert(metric)
    with pytest.raises(IntegrityError): repo.insert(metric.model_copy(update={"id":uuid4()}))


def test_failure_listing_and_aggregates(analytics):
    db, _, _, conversations, _, run_record = analytics; result = conversations.insert(conversation(run_record.id, outcome=FinalOutcome.FAILED)); repo = BenchmarkFailureRepository(db)
    repo.insert(FailureEventRecord(conversation_result_id=result.id, failure_category=FailureCategory.BUSINESS_DATA, failure_code="missing", severity=FailureSeverity.WARNING, is_primary=True, description="Data missing.", responsibility_layer=ResponsibilityLayer.BUSINESS_DATA, created_at=NOW))
    assert len(repo.list_by_conversation(result.id)) == 1
    assert repo.aggregate_by_category(run_record.id) == {"business_data": 1}
    assert repo.aggregate_by_responsibility_layer(run_record.id) == {"business_data": 1}


def test_run_delete_cascades_only_analytics_children(analytics):
    db, suites, runs, conversations, suite_record, run_record = analytics
    conversations.insert(conversation(run_record.id)); assert runs.delete(run_record.id)
    assert conversations.list_by_run(run_record.id) == ()
    assert suites.get_by_id(suite_record.id) is not None
