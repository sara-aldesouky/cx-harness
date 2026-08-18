from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.benchmark_analytics.contracts import (
    BenchmarkRunDefinition, BenchmarkRunSummary, BenchmarkSuiteDefinition,
    ConversationResultRecord, DeploymentMode, EvaluationMethod, FailureCategory,
    FailureEventRecord, FailureSeverity, FinalOutcome, MetricResultRecord,
    ModelConfigurationSnapshot, PricingSnapshot, ProviderTurnRecord, ProviderType,
    ResponsibilityLayer, ToolExecutionRecord,
)

NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def suite(**updates):
    values = dict(suite_key="cx-v1", name="CX", description="Benchmark", version="1.0", test_case_count=100, content_hash="sha256:abc", created_at=NOW, updated_at=NOW)
    values.update(updates); return BenchmarkSuiteDefinition(**values)


def run(**updates):
    values = dict(run_key="RUN-1", benchmark_suite_id=uuid4(), model_name="qwen3:8b", provider_name="ollama", provider_type=ProviderType.LOCAL_RUNTIME, deployment_mode=DeploymentMode.LOCAL, configuration_snapshot=ModelConfigurationSnapshot(maximum_output_tokens=256), pricing_snapshot=PricingSnapshot(hardware_hourly_cost=Decimal("1.25")), created_at=NOW, updated_at=NOW)
    values.update(updates); return BenchmarkRunDefinition(**values)


def conversation(**updates):
    values = dict(benchmark_run_id=uuid4(), test_case_key="TC-001", language="ar-EG", category="orders", expected_intent="track order", final_outcome=FinalOutcome.PASSED, passed=True, provider_turn_count=1, customer_turn_count=1, tool_execution_count=1, successful_tool_execution_count=1, input_tokens=10, output_tokens=5, total_tokens=15, total_latency_ms=Decimal("12.5"), started_at=NOW, completed_at=NOW + timedelta(seconds=1), created_at=NOW)
    values.update(updates); return ConversationResultRecord(**values)


def test_suite_is_immutable_and_round_trips_json():
    value = suite(); assert BenchmarkSuiteDefinition.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError): value.name = "changed"


@pytest.mark.parametrize("updates", [{"test_case_count": 0}, {"suite_key": " "}, {"updated_at": NOW-timedelta(seconds=1)}])
def test_invalid_suite_values_are_rejected(updates):
    with pytest.raises(ValidationError): suite(**updates)


def test_configuration_and_pricing_preserve_decimals():
    value = run(); assert isinstance(value.pricing_snapshot.hardware_hourly_cost, Decimal)
    assert BenchmarkRunDefinition.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("updates", [{"temperature": Decimal("2.1")}, {"top_p": Decimal("1.1")}, {"maximum_output_tokens": 0}, {"timeout_seconds": Decimal("0")}])
def test_invalid_configuration_is_rejected(updates):
    with pytest.raises(ValidationError): ModelConfigurationSnapshot(**updates)


@pytest.mark.parametrize("field", ["api_key", "access_token", "customer_id", "email", "delivery_address"])
def test_sensitive_configuration_keys_are_rejected(field):
    with pytest.raises(ValidationError): ModelConfigurationSnapshot(provider_settings={field: "secret"})


def test_raw_order_identifier_is_rejected_but_masked_identifier_is_allowed():
    with pytest.raises(ValidationError): ModelConfigurationSnapshot(provider_settings={"reference": "CX-SYN-2026-0001"})
    assert ModelConfigurationSnapshot(provider_settings={"reference": "CX-SYN-20********01"})


@pytest.mark.parametrize("updates", [{"total_tokens": 14}, {"tool_execution_count": 2}, {"estimated_cost": Decimal("1")}, {"total_latency_ms": Decimal("-1")}])
def test_conversation_aggregate_invariants(updates):
    with pytest.raises(ValidationError): conversation(**updates)


def test_money_requires_decimal_and_currency_pair():
    value = conversation(estimated_cost=Decimal("0.12500000"), currency_code="usd")
    assert value.currency_code == "USD" and value.estimated_cost == Decimal("0.12500000")


def test_provider_turn_validation_and_serialization():
    value = ProviderTurnRecord(conversation_result_id=uuid4(), turn_number=1, finish_reason="stop", input_tokens=3, output_tokens=2, total_tokens=5, latency_ms=Decimal("1.2"), context_utilization_ratio=Decimal("0.5"), created_at=NOW)
    assert ProviderTurnRecord.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError): value.turn_number = 2


@pytest.mark.parametrize("updates", [{"turn_number": 0}, {"total_tokens": 1}, {"context_utilization_ratio": Decimal("1.1")}])
def test_invalid_provider_turns(updates):
    values = dict(conversation_result_id=uuid4(), turn_number=1, finish_reason="stop", total_tokens=0, created_at=NOW); values.update(updates)
    with pytest.raises(ValidationError): ProviderTurnRecord(**values)


def test_tool_execution_sanitization_and_ordering_contract():
    value = ToolExecutionRecord(conversation_result_id=uuid4(), execution_order=1, tool_name="get_order_status", selection_correct=True, arguments_valid=True, authorization_passed=True, execution_successful=True, sanitized_arguments={"order_reference":"CX-SYN-20********01"}, created_at=NOW)
    assert value.execution_order == 1
    with pytest.raises(ValidationError): ToolExecutionRecord(**{**value.model_dump(), "execution_order": 0})


def test_tool_execution_rejects_unredacted_identifier():
    with pytest.raises(ValidationError): ToolExecutionRecord(conversation_result_id=uuid4(), execution_order=1, tool_name="x", selection_correct=True, arguments_valid=True, authorization_passed=True, execution_successful=True, sanitized_arguments={"reference":"ORD-10025"}, created_at=NOW)


@pytest.mark.parametrize("values", [dict(value_numeric=Decimal("1"), value_boolean=True), {}, dict(value_text="ok", value_numeric=Decimal("1"))])
def test_metric_requires_exactly_one_value(values):
    with pytest.raises(ValidationError): MetricResultRecord(conversation_result_id=uuid4(), metric_key="grounding", metric_version="1", evaluation_method=EvaluationMethod.DETERMINISTIC_RULE, evaluator_name="rules", evaluator_version="1", created_at=NOW, **values)


def test_metric_version_and_method_are_retained():
    value = MetricResultRecord(conversation_result_id=uuid4(), metric_key="grounding", metric_version="2", value_boolean=True, normalized_score=Decimal("1"), evaluation_method=EvaluationMethod.HUMAN_REVIEW, evaluator_name="reviewer", evaluator_version="3", created_at=NOW)
    assert value.metric_version == "2" and value.evaluation_method is EvaluationMethod.HUMAN_REVIEW


def test_failure_responsibility_is_explicit():
    value = FailureEventRecord(conversation_result_id=uuid4(), failure_category=FailureCategory.BUSINESS_DATA, failure_code="payment_not_found", severity=FailureSeverity.WARNING, is_primary=True, description="Payment data unavailable.", responsibility_layer=ResponsibilityLayer.BUSINESS_DATA, created_at=NOW)
    assert value.responsibility_layer is ResponsibilityLayer.BUSINESS_DATA


def test_summary_reconciles_outcomes():
    with pytest.raises(ValidationError): BenchmarkRunSummary(benchmark_run_id=uuid4(), conversation_count=1, passed_count=1, failed_count=1, degraded_count=0, provider_turn_count=0, tool_execution_count=0, successful_tool_execution_count=0, input_tokens=0, output_tokens=0, total_latency_ms=Decimal("0"))


def test_unknown_contract_fields_are_rejected():
    with pytest.raises(ValidationError): suite(unknown="value")
