from datetime import datetime,timedelta,timezone
from decimal import Decimal
from uuid import uuid4
import pytest
from pydantic import ValidationError

from app.benchmark_analytics.contracts import *
from app.benchmark_reporting.aggregation import *
from app.benchmark_reporting.comparison import compare_reports,select_winner
from app.benchmark_reporting.contracts import *
from app.benchmark_reporting.errors import IncompatibleComparisonError
from app.benchmark_reporting.scoring import score_model
from app.benchmark_reporting.service import BenchmarkReportingService

NOW=datetime(2026,7,29,tzinfo=timezone.utc)

def snapshot(model="qwen",run_key="run-1",currency=True,content_hash="hash"):
    suite=BenchmarkSuiteDefinition(suite_key="suite",name="Suite",description="D",version="1",test_case_count=3,content_hash=content_hash,status=SuiteStatus.FROZEN,created_at=NOW,updated_at=NOW)
    pricing=PricingSnapshot(currency_code="USD",input_cost_per_million_tokens=Decimal("2"),output_cost_per_million_tokens=Decimal("4"),request_cost=Decimal(".01"))
    run=BenchmarkRunDefinition(run_key=run_key,benchmark_suite_id=suite.id,model_name=model,provider_name="provider",provider_type=ProviderType.API,deployment_mode=DeploymentMode.MANAGED_API,configuration_snapshot=ModelConfigurationSnapshot(),pricing_snapshot=pricing,status=RunStatus.COMPLETED,started_at=NOW,completed_at=NOW+timedelta(seconds=3),created_at=NOW,updated_at=NOW)
    conversations=[]; turns=[]; tools=[]; metrics=[]; failures=[]
    for i,(passed,lang,category,complexity,pressure) in enumerate([(True,"ar-EG","orders","low","low"),(False,"en","payments","high","high"),(True,"franco","orders","high","low")],1):
        cid=uuid4(); cost=Decimal(".10") if currency else None
        conversations.append(ConversationResultRecord(id=cid,benchmark_run_id=run.id,test_case_key=f"TC-{i}",language=lang,category=category,complexity_level=complexity,pressure_level=pressure,expected_intent="lookup",actual_intent="lookup" if passed else "other",final_outcome=FinalOutcome.PASSED if passed else FinalOutcome.FAILED,passed=passed,failure_category=None if passed else FailureCategory.MODEL_REASONING,provider_turn_count=1,customer_turn_count=i,clarification_count=0 if passed else 1,tool_execution_count=1,successful_tool_execution_count=1 if passed else 0,failed_tool_execution_count=0 if passed else 1,hallucination_detected=not passed,grounding_failure_detected=not passed,input_tokens=10*i,output_tokens=5*i,total_tokens=15*i,total_latency_ms=Decimal(100*i),estimated_cost=cost,currency_code="USD" if currency else None,started_at=NOW+timedelta(seconds=i),completed_at=NOW+timedelta(seconds=i+1),created_at=NOW))
        tid=uuid4(); turns.append(ProviderTurnRecord(id=tid,conversation_result_id=cid,turn_number=1,finish_reason="stop",input_tokens=10*i,output_tokens=5*i,total_tokens=15*i,latency_ms=Decimal(80*i),context_tokens_used=1000*i,context_window_limit=8000,context_utilization_ratio=Decimal(1000*i)/Decimal(8000),response_valid=True,created_at=NOW))
        tools.append(ToolExecutionRecord(conversation_result_id=cid,provider_turn_id=tid,execution_order=1,tool_name="lookup",expected_tool="lookup",selection_correct=passed,arguments_valid=passed,authorization_passed=True,execution_successful=passed,business_failure=False,failure_code=None if passed else "runtime_error",latency_ms=Decimal(20*i),created_at=NOW))
        for key,value in [("conversation_completion",passed),("tool_selection_match_rate",passed),("argument_validation_rate",passed),("grounding_enforcement_rate",passed)]:
            metrics.append(MetricResultRecord(conversation_result_id=cid,metric_key=key,metric_version="1",value_boolean=value,normalized_score=Decimal(int(value)),evaluation_method=EvaluationMethod.DETERMINISTIC_RULE,evaluator_name="rules",evaluator_version="1",created_at=NOW))
        if not passed:
            failures.extend([FailureEventRecord(conversation_result_id=cid,failure_category=FailureCategory.MODEL_REASONING,failure_code="reason",severity=FailureSeverity.ERROR,is_primary=True,description="Model failure",responsibility_layer=ResponsibilityLayer.MODEL,created_at=NOW),FailureEventRecord(conversation_result_id=cid,failure_category=FailureCategory.MODEL_REASONING,failure_code="reason2",severity=FailureSeverity.WARNING,is_primary=False,description="Secondary",responsibility_layer=ResponsibilityLayer.MODEL,created_at=NOW)])
    return RunAnalyticsSnapshot(suite=suite,run=run,conversations=tuple(conversations),provider_turns=tuple(turns),tool_executions=tuple(tools),metrics=tuple(metrics),failures=tuple(failures))

class FakeRepo:
    def __init__(self,value):self.value=value
    def load_run(self,run_id):return self.value

def policy(**changes):
    data=dict(policy_key="core",policy_version="1",metric_weights={"conversation_completion":Decimal(".4"),"tool_selection_match_rate":Decimal(".3"),"argument_validation_rate":Decimal(".2"),"grounding_enforcement_rate":Decimal(".1")});data.update(changes);return ScoringPolicy(**data)

def report(value=None):return BenchmarkReportingService(FakeRepo(value or snapshot()),clock=lambda:NOW).generate_run_report((value or snapshot()).run.id,policy())

@pytest.mark.parametrize("weights",[{}, {"a":Decimal(".9")},{"a":Decimal("1.1")},{"a":Decimal("-.1"),"b":Decimal("1.1")}])
def test_scoring_weights_must_be_valid(weights):
    with pytest.raises(ValidationError):ScoringPolicy(policy_key="x",policy_version="1",metric_weights=weights)

def test_contracts_immutable_and_json_serializable():
    value=report(); assert BenchmarkRunReport.model_validate_json(value.model_dump_json())==value
    with pytest.raises(ValidationError):value.suite_key="other"

def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):ScoringPolicy(policy_key="x",policy_version="1",metric_weights={"a":Decimal("1")},unknown=True)

def test_metric_versions_not_combined():
    items=list(snapshot().metrics); items.append(items[0].model_copy(update={"id":uuid4(),"metric_version":"2"}))
    assert len([m for m in aggregate_metrics(items) if m.metric_key=="conversation_completion"])==2

@pytest.mark.parametrize("field,expected",[("normalized_average",Decimal(".6666666666666666666666666667")),("true_rate",Decimal(".6666666666666666666666666667")),("true_count",2),("false_count",1)])
def test_metric_statistics(field,expected):
    item=next(m for m in aggregate_metrics(snapshot().metrics) if m.metric_key=="conversation_completion"); assert getattr(item,field)==expected

@pytest.mark.parametrize("attribute,contract,count",[("language",LanguagePerformanceSummary,3),("category",CategoryPerformanceSummary,2),("complexity_level",ComplexityPerformanceSummary,2),("pressure_level",PressurePerformanceSummary,2)])
def test_segment_breakdowns(attribute,contract,count):assert len(segment_summaries(snapshot(),attribute,contract))==count

def test_segment_missing_category_not_invented():assert {x.segment for x in segment_summaries(snapshot(),"language",LanguagePerformanceSummary)}=={"ar-EG","en","franco"}

@pytest.mark.parametrize("field,expected",[("expected_count",3),("selected_count",3),("correct_selection_count",2),("incorrect_selection_count",1),("successful_execution_count",2),("runtime_failure_count",1)])
def test_tool_statistics(field,expected):assert getattr(aggregate_tools(snapshot())[0],field)==expected

def test_tool_failure_distinctions():
    item=aggregate_tools(snapshot())[0]; assert item.business_failure_count==0 and item.failure_code_distribution=={"runtime_error":1}

def test_failure_events_deduplicate_affected_conversations():
    item=aggregate_failures(snapshot(),"failure_category",FailureCategorySummary)[0]; assert item.event_count==2 and item.affected_conversation_count==1

def test_failure_responsibility_summary():assert aggregate_failures(snapshot(),"responsibility_layer",FailureResponsibilitySummary)[0].responsibility_layer=="model"

@pytest.mark.parametrize("field,expected",[("total_input_tokens",60),("total_output_tokens",30),("total_tokens",90),("median_tokens_per_conversation",Decimal("30")),("minimum_tokens",15),("maximum_tokens",45)])
def test_token_statistics(field,expected):assert getattr(aggregate_tokens(snapshot()),field)==expected

@pytest.mark.parametrize("field,expected",[("accumulated_provider_latency_ms",Decimal("480")),("accumulated_tool_latency_ms",Decimal("120")),("p50_ms",Decimal("200")),("minimum_conversation_latency_ms",Decimal("100")),("maximum_conversation_latency_ms",Decimal("300"))])
def test_latency_statistics(field,expected):assert getattr(aggregate_latency(snapshot()),field)==expected

def test_context_usage_is_distinct_from_limit():
    value=aggregate_context(snapshot()); assert value.total_context_tokens==6000 and value.maximum_context_tokens==3000 and value.maximum_utilization_ratio==Decimal(".375")

def test_context_buckets_and_threshold():
    value=aggregate_context(snapshot(),Decimal(".3")); assert value.conversations_above_threshold==1 and sum(x.conversation_count for x in value.buckets)==3

def test_managed_cost_summary():
    value=aggregate_cost(snapshot()); assert value.available and value.total_estimated_cost==Decimal(".30") and value.currency_code=="USD"

def test_unknown_cost_not_free():
    value=aggregate_cost(snapshot(currency=False)); assert not value.available and value.total_estimated_cost is None

def test_intent_confusion():
    value=aggregate_intent(snapshot()); assert value.exact_match_count==2 and value.unsupported_intent_count==1 and len(value.confusion)==2

def test_score_renormalizes_missing_metrics():
    value=snapshot(); metrics=tuple(m for m in aggregate_metrics(value.metrics) if m.metric_key!="grounding_enforcement_rate")
    score=score_model(value,metrics,policy()); assert score.overall_score is not None and score.score_coverage==Decimal(".9") and "grounding_enforcement_rate" in score.missing_dimensions

def test_score_require_all_returns_unavailable():
    value=snapshot(); metrics=tuple(m for m in aggregate_metrics(value.metrics) if m.metric_key!="grounding_enforcement_rate")
    score=score_model(value,metrics,policy(missing_metric_behavior=MissingMetricBehavior.REQUIRE_ALL)); assert score.overall_score is None

def test_run_report_completion_and_outcomes():
    value=report(); assert value.completion.pass_rate==Decimal(2)/Decimal(3) and value.outcomes.counts=={"failed":1,"passed":2}

def test_run_report_contains_all_breakdowns():
    value=report(); assert value.languages and value.categories and value.complexity and value.pressure and value.tools

def test_dataset_without_comparison():
    service=BenchmarkReportingService(FakeRepo(snapshot()),clock=lambda:NOW); value=service.generate_dataset((snapshot().run.id,),policy()); assert value.dataset.comparison is None

def test_service_compare_runs():
    one=snapshot(run_key="one"); two=snapshot(model="gemini",run_key="two")
    class MappingRepo:
        def load_run(self,run_id): return {one.run.id:one,two.run.id:two}[run_id]
    value=BenchmarkReportingService(MappingRepo(),clock=lambda:NOW).compare_runs((one.run.id,two.run.id),policy())
    assert len(value.runs)==2

@pytest.mark.parametrize("direction,expected",[(WinnerDirection.HIGHER,"a"),(WinnerDirection.LOWER,"b")])
def test_contextual_winner(direction,expected):assert select_winner("x",{"a":Decimal("2"),"b":Decimal("1")},direction).winning_run_key==expected

def test_winner_tie():assert select_winner("x",{"a":Decimal("1"),"b":Decimal("1")},WinnerDirection.HIGHER).tie
def test_winner_unavailable():assert not select_winner("x",{"a":None},WinnerDirection.HIGHER).available

def test_compatible_model_comparison():
    one=report(snapshot(run_key="one"));two=report(snapshot(model="gemini",run_key="two"));value=compare_reports((one,two),policy(),NOW);assert len(value.runs)==2 and value.winners

def test_incompatible_suite_comparison_rejected():
    with pytest.raises(IncompatibleComparisonError):compare_reports((report(snapshot(run_key="one")),report(snapshot(run_key="two",content_hash="different"))),policy(),NOW)

def test_single_run_comparison_rejected():
    with pytest.raises(IncompatibleComparisonError):compare_reports((report(),),policy(),NOW)

def test_cost_winner_unavailable_for_missing_cost():
    one=report(snapshot(run_key="one"));two=report(snapshot(run_key="two",currency=False));value=compare_reports((one,two),policy(),NOW);assert not value.cost_ranking_available
