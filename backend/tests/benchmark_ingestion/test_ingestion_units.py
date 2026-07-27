from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.benchmark_analytics.contracts import (
    DeploymentMode, FailureCategory, FailureSeverity, ModelConfigurationSnapshot,
    PricingSnapshot, ProviderType, ResponsibilityLayer,
)
from app.benchmark_ingestion.contracts import (
    BenchmarkExecutionIngestionRequest, BenchmarkRunIdentity,
    CompletedConversationExecution, DeterministicEvaluationArtifact,
    DeterministicFailureSignal, ProviderTurnExecution, RuntimeTerminationArtifact,
    ToolExecutionArtifact, UsageArtifact,
)
from app.benchmark_ingestion.costing import BenchmarkCostCalculator
from app.benchmark_ingestion.errors import (
    IngestionPricingError, IngestionSanitizationError, IngestionValidationError,
)
from app.benchmark_ingestion.mappers import (
    calculate_latency, calculate_usage, map_conversation, map_failures, map_metrics,
    map_tools, map_turns,
)
from app.benchmark_ingestion.sanitization import sanitize_mapping, sanitize_text
from app.benchmark_ingestion.backfill import build_stage_15_3_backfill

NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def identity(**changes):
    data = dict(
        suite_key="cx-pilot", suite_version="1", run_key="RUN-1", model_name="qwen3:8b",
        provider_name="ollama", provider_type=ProviderType.LOCAL_RUNTIME,
        deployment_mode=DeploymentMode.LOCAL,
        configuration_snapshot=ModelConfigurationSnapshot(context_window_limit=8192),
        pricing_snapshot=PricingSnapshot(),
    ); data.update(changes); return BenchmarkRunIdentity(**data)


def turn(number=1, **changes):
    data = dict(turn_number=number, finish_reason="stop", usage=UsageArtifact(input_tokens=10, output_tokens=2, total_tokens=12), latency_ms=Decimal("5"), occurred_at=NOW)
    data.update(changes); return ProviderTurnExecution(**data)


def tool(order=1, **changes):
    data = dict(execution_order=order, provider_turn_number=1, tool_name="list_current_orders", expected_tool="list_current_orders", selection_correct=True, arguments_valid=True, authorization_passed=True, execution_successful=True, latency_ms=Decimal("2"), arguments={"reference":"ORD-*****25"}, result_summary={"status":"ok"}, occurred_at=NOW)
    data.update(changes); return ToolExecutionArtifact(**data)


def conversation(**changes):
    data = dict(test_case_key="TC-001", language="ar-EG", category="orders", expected_intent="track_order", actual_intent="track_order", customer_turn_count=2, provider_turns=(turn(),), tool_executions=(tool(),), termination=RuntimeTerminationArtifact(reason="final_response",runtime_completed=True,task_completed=True), evaluation=DeterministicEvaluationArtifact(grounding_enforced=True,continuity_resolved=True,acceptance_criteria_passed=True), started_at=NOW, completed_at=NOW+timedelta(seconds=1))
    data.update(changes); return CompletedConversationExecution(**data)


def test_contracts_are_immutable():
    with pytest.raises(ValidationError): identity().run_key = "other"


@pytest.mark.parametrize("factory", [identity, turn, tool, conversation])
def test_contracts_reject_unknown_fields(factory):
    with pytest.raises(ValidationError): factory(unknown=True)


def test_json_round_trip():
    value=conversation(); assert CompletedConversationExecution.model_validate_json(value.model_dump_json()) == value


def test_timestamps_normalize_to_utc():
    value=turn(occurred_at=datetime(2026,7,28,3,tzinfo=timezone(timedelta(hours=3))))
    assert value.occurred_at.hour == 0 and value.occurred_at.tzinfo == timezone.utc


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError): turn(occurred_at=datetime(2026,1,1))


@pytest.mark.parametrize("values", [(-1,0,-1),(1,1,3)])
def test_usage_rejects_invalid_totals(values):
    with pytest.raises(ValidationError): UsageArtifact(input_tokens=values[0],output_tokens=values[1],total_tokens=values[2])


def test_duplicate_case_request_rejected():
    with pytest.raises(ValidationError): BenchmarkExecutionIngestionRequest(identity=identity(),conversations=(conversation(),conversation()))


def test_turn_order_must_be_contiguous():
    with pytest.raises(ValidationError): conversation(provider_turns=(turn(2),))


def test_tool_order_must_be_contiguous():
    with pytest.raises(ValidationError): conversation(tool_executions=(tool(2),))


def test_usage_and_latency_are_recomputed():
    value=conversation(); assert calculate_usage(value)==(10,2,12); assert calculate_latency(value)==Decimal("7")


def test_supplied_usage_mismatch_rejected():
    value=conversation(supplied_usage=UsageArtifact(input_tokens=1,output_tokens=1,total_tokens=2))
    with pytest.raises(IngestionValidationError): calculate_usage(value)


def test_supplied_latency_mismatch_rejected():
    with pytest.raises(IngestionValidationError): calculate_latency(conversation(supplied_latency_ms=Decimal("99")))


@pytest.mark.parametrize("unsafe", [
    {"email":"x@example.com"},{"phone":"+201234567890"},{"delivery_address":"street"},
    {"api_key":"secret"},{"authorization":"Bearer secret"},{"database_url":"postgresql://u:p@h/d"},
    {"customer_id":"abc"},
])
def test_sensitive_keys_are_rejected(unsafe):
    with pytest.raises(IngestionSanitizationError): sanitize_mapping(unsafe)


@pytest.mark.parametrize("unsafe", ["x@example.com","+201234567890","ORD-10025","postgresql://u:p@h/d"])
def test_sensitive_text_is_rejected(unsafe):
    with pytest.raises(IngestionSanitizationError): sanitize_text(unsafe)


def test_safe_masked_reference_and_defensive_copy():
    source={"items":[{"reference":"ORD-*****25"}]}; result=sanitize_mapping(source)
    source["items"][0]["reference"]="changed"; assert result["items"][0]["reference"]=="ORD-*****25"


@pytest.mark.parametrize("input_tokens,output_tokens,requests,expected", [
    (1000,0,0,"0.002"),(0,1000,0,"0.004"),(0,0,2,"0.02"),(1000,1000,1,"0.016"),
])
def test_api_cost_calculation(input_tokens,output_tokens,requests,expected):
    pricing=PricingSnapshot(currency_code="USD",input_cost_per_million_tokens=Decimal("2"),output_cost_per_million_tokens=Decimal("4"),request_cost=Decimal("0.01"))
    result=BenchmarkCostCalculator().calculate(pricing,input_tokens,output_tokens,requests,DeploymentMode.MANAGED_API)
    assert result.amount == Decimal(expected) and result.currency_code == "USD"


def test_missing_pricing_is_unknown_not_zero():
    result=BenchmarkCostCalculator().calculate(PricingSnapshot(),1,1,1,DeploymentMode.MANAGED_API)
    assert result.amount is None and result.evidence["reason"]=="pricing_unavailable"


def test_per_thousand_pricing():
    pricing=PricingSnapshot(input_cost_per_million_tokens=Decimal("2"),assumptions={"pricing_unit":"per_thousand"})
    result=BenchmarkCostCalculator().calculate(pricing,1000,0,0,DeploymentMode.MANAGED_API)
    assert result.amount == Decimal("2")


def test_unknown_pricing_unit_rejected():
    pricing=PricingSnapshot(input_cost_per_million_tokens=Decimal("2"),assumptions={"pricing_unit":"per_request_token"})
    with pytest.raises(IngestionPricingError): BenchmarkCostCalculator().calculate(pricing,1,0,0,DeploymentMode.MANAGED_API)


def test_self_hosted_cost_is_not_invented():
    result=BenchmarkCostCalculator().calculate(PricingSnapshot(hardware_hourly_cost=Decimal("2")),1,1,1,DeploymentMode.SELF_HOSTED)
    assert result.amount is None and result.evidence["reason"]=="self_hosted_allocation_unavailable"


def test_negative_cost_input_rejected():
    with pytest.raises(IngestionPricingError): BenchmarkCostCalculator().calculate(PricingSnapshot(),-1,0,0,DeploymentMode.MANAGED_API)


def test_mapping_calculates_counts_and_metrics():
    value=conversation(); cost=BenchmarkCostCalculator().calculate(PricingSnapshot(),10,2,1,DeploymentMode.LOCAL)
    record=map_conversation(value, __import__('uuid').uuid4(), cost, NOW)
    metrics=map_metrics(value,record,cost,NOW)
    assert record.provider_turn_count==1 and record.tool_execution_count==1
    assert {m.metric_key for m in metrics} >= {"conversation_completion","grounding_enforcement_rate","continuity_resolution_rate"}


def test_turn_mapping_preserves_order_and_context_ratio():
    value=conversation(provider_turns=(turn(context_tokens_used=4000,context_window_limit=8000),))
    records,ids=map_turns(value,__import__('uuid').uuid4()); assert records[0].context_utilization_ratio==Decimal("0.5") and 1 in ids


def test_tool_mapping_rejects_unknown_turn():
    with pytest.raises(IngestionValidationError): map_tools(conversation(tool_executions=(tool(provider_turn_number=2),)),__import__('uuid').uuid4(),{1:__import__('uuid').uuid4()})


def test_failure_mapping_preserves_ownership():
    signal=DeterministicFailureSignal(category=FailureCategory.PROVIDER_FAILURE,code="timeout",severity=FailureSeverity.ERROR,responsibility_layer=ResponsibilityLayer.PROVIDER,description="Provider timed out",is_primary=True,provider_turn_number=1)
    value=conversation(evaluation=DeterministicEvaluationArtifact(acceptance_criteria_passed=False,failures=(signal,)))
    records=map_failures(value,__import__('uuid').uuid4(),{1:__import__('uuid').uuid4()},{},NOW)
    assert records[0].responsibility_layer is ResponsibilityLayer.PROVIDER


def test_failure_mapping_rejects_unknown_child():
    signal=DeterministicFailureSignal(category=FailureCategory.RUNTIME,code="bad",severity=FailureSeverity.ERROR,responsibility_layer=ResponsibilityLayer.HARNESS,description="Runtime failed",tool_execution_order=4)
    value=conversation(evaluation=DeterministicEvaluationArtifact(acceptance_criteria_passed=False,failures=(signal,)))
    with pytest.raises(IngestionValidationError): map_failures(value,__import__('uuid').uuid4(),{1:__import__('uuid').uuid4()},{1:__import__('uuid').uuid4()},NOW)


def test_stage_15_3_backfill_is_deterministic_and_sanitized():
    first=build_stage_15_3_backfill(); second=build_stage_15_3_backfill()
    assert first == second and len(first.conversations)==2
    sanitize_mapping(first.model_dump(mode="json"))
