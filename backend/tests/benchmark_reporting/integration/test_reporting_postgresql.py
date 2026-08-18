from datetime import datetime,timedelta,timezone
from decimal import Decimal
import pytest
from sqlalchemy import func,select
from app.benchmark_analytics.contracts import *
from app.benchmark_analytics.repositories import *
from app.benchmark_reporting.contracts import ScoringPolicy
from app.benchmark_reporting.repositories import BenchmarkReportingRepository
from app.benchmark_reporting.service import BenchmarkReportingService
from app.benchmark_reporting.errors import RunNotFoundError
from app.database.models import BenchmarkConversationResult

pytestmark=pytest.mark.integration
NOW=datetime(2026,7,29,tzinfo=timezone.utc)

@pytest.fixture
def stored_run(db_session):
    suite=BenchmarkSuiteRepository(db_session).create(BenchmarkSuiteDefinition(suite_key="reporting",name="Reporting",description="D",version="1",test_case_count=1,content_hash="hash",status=SuiteStatus.FROZEN,created_at=NOW,updated_at=NOW))
    run=BenchmarkRunRepository(db_session).create(BenchmarkRunDefinition(run_key="report-run",benchmark_suite_id=suite.id,model_name="qwen",provider_name="ollama",provider_type=ProviderType.LOCAL_RUNTIME,deployment_mode=DeploymentMode.LOCAL,configuration_snapshot=ModelConfigurationSnapshot(),pricing_snapshot=PricingSnapshot(),status=RunStatus.COMPLETED,started_at=NOW,completed_at=NOW+timedelta(seconds=1),created_at=NOW,updated_at=NOW))
    conversation=BenchmarkConversationResultRepository(db_session).insert(ConversationResultRecord(benchmark_run_id=run.id,test_case_key="TC-1",language="ar-EG",category="orders",complexity_level="high",pressure_level="medium",expected_intent="track",actual_intent="track",final_outcome=FinalOutcome.PASSED,passed=True,provider_turn_count=1,customer_turn_count=2,tool_execution_count=1,successful_tool_execution_count=1,input_tokens=10,output_tokens=5,total_tokens=15,total_latency_ms=Decimal("30"),started_at=NOW,completed_at=NOW+timedelta(seconds=1),created_at=NOW))
    turn=BenchmarkProviderTurnRepository(db_session).insert(ProviderTurnRecord(conversation_result_id=conversation.id,turn_number=1,finish_reason="stop",input_tokens=10,output_tokens=5,total_tokens=15,latency_ms=Decimal("20"),context_tokens_used=1000,context_window_limit=8000,context_utilization_ratio=Decimal(".125"),created_at=NOW))
    BenchmarkToolExecutionRepository(db_session).insert(ToolExecutionRecord(conversation_result_id=conversation.id,provider_turn_id=turn.id,execution_order=1,tool_name="get_order_status",expected_tool="get_order_status",selection_correct=True,arguments_valid=True,authorization_passed=True,execution_successful=True,latency_ms=Decimal("10"),created_at=NOW))
    for key in ("conversation_completion","tool_selection_match_rate"):
        BenchmarkMetricRepository(db_session).insert(MetricResultRecord(conversation_result_id=conversation.id,metric_key=key,metric_version="1",value_boolean=True,normalized_score=Decimal("1"),evaluation_method=EvaluationMethod.DETERMINISTIC_RULE,evaluator_name="rules",evaluator_version="1",created_at=NOW))
    return run

def policy():return ScoringPolicy(policy_key="db",policy_version="1",metric_weights={"conversation_completion":Decimal(".5"),"tool_selection_match_rate":Decimal(".5")})

def test_repository_loads_ordered_typed_snapshot(db_session,stored_run):
    value=BenchmarkReportingRepository(db_session).load_run(stored_run.id)
    assert value.run==stored_run and value.provider_turns[0].turn_number==1 and value.tool_executions[0].execution_order==1

def test_reporting_service_uses_postgresql_without_writes(db_session,stored_run):
    before=db_session.scalar(select(func.count()).select_from(BenchmarkConversationResult)); db_session.flush()
    value=BenchmarkReportingService(BenchmarkReportingRepository(db_session),clock=lambda:NOW).generate_run_report(stored_run.id,policy())
    after=db_session.scalar(select(func.count()).select_from(BenchmarkConversationResult))
    assert value.completion.pass_rate==Decimal("1") and before==after and not db_session.new and not db_session.dirty and not db_session.deleted

def test_unknown_run_is_clear(db_session):
    with pytest.raises(RunNotFoundError):BenchmarkReportingRepository(db_session).load_run(__import__('uuid').uuid4())
