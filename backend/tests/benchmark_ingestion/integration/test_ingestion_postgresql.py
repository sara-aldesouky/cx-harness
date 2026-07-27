from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.benchmark_analytics.contracts import (
    BenchmarkSuiteDefinition, DeploymentMode, ModelConfigurationSnapshot,
    PricingSnapshot, ProviderType, RunStatus,
)
from app.benchmark_analytics.repositories import (
    BenchmarkConversationResultRepository, BenchmarkMetricRepository,
    BenchmarkProviderTurnRepository, BenchmarkRunRepository,
    BenchmarkSuiteRepository, BenchmarkToolExecutionRepository,
)
from app.benchmark_ingestion.contracts import (
    BenchmarkExecutionIngestionRequest, BenchmarkRunIdentity,
    CompletedConversationExecution, DeterministicEvaluationArtifact,
    IngestionItemStatus, ProviderTurnExecution, RuntimeTerminationArtifact,
    ToolExecutionArtifact, UsageArtifact,
)
from app.benchmark_ingestion.errors import IngestionConflictError, IngestionLifecycleError
from app.benchmark_ingestion.service import BenchmarkIngestionService
from app.database.models import BenchmarkConversationResult
from app.database.models.benchmark_analytics import BenchmarkProviderTurn

pytestmark=pytest.mark.integration
NOW=datetime(2026,7,28,tzinfo=timezone.utc)


def identity(run_key="INGEST-1"):
    return BenchmarkRunIdentity(suite_key="ingestion-suite",suite_version="1",run_key=run_key,model_name="qwen3:8b",provider_name="ollama",provider_type=ProviderType.LOCAL_RUNTIME,deployment_mode=DeploymentMode.LOCAL,configuration_snapshot=ModelConfigurationSnapshot(context_window_limit=8192),pricing_snapshot=PricingSnapshot())


def conversation(key="TC-001", output=2):
    turn=ProviderTurnExecution(turn_number=1,finish_reason="tool_calls",usage=UsageArtifact(input_tokens=10,output_tokens=1,total_tokens=11),latency_ms=Decimal("3"),occurred_at=NOW)
    turn2=ProviderTurnExecution(turn_number=2,finish_reason="stop",usage=UsageArtifact(input_tokens=12,output_tokens=output,total_tokens=12+output),latency_ms=Decimal("4"),occurred_at=NOW)
    tool=ToolExecutionArtifact(execution_order=1,provider_turn_number=1,tool_name="list_current_orders",expected_tool="list_current_orders",selection_correct=True,arguments_valid=True,authorization_passed=True,execution_successful=True,latency_ms=Decimal("2"),arguments={},result_summary={"count":1},occurred_at=NOW)
    return CompletedConversationExecution(test_case_key=key,language="ar-EG",category="orders",expected_intent="list_orders",actual_intent="list_orders",customer_turn_count=1,provider_turns=(turn,turn2),tool_executions=(tool,),termination=RuntimeTerminationArtifact(reason="final_response",runtime_completed=True,task_completed=True),evaluation=DeterministicEvaluationArtifact(grounding_enforced=True,continuity_resolved=True,acceptance_criteria_passed=True),started_at=NOW,completed_at=NOW+timedelta(seconds=1))


@pytest.fixture
def ingestion(db_session):
    suite=BenchmarkSuiteDefinition(suite_key="ingestion-suite",name="Ingestion Suite",description="Tests",version="1",test_case_count=2,content_hash="sha256:ingestion",created_at=NOW,updated_at=NOW)
    BenchmarkSuiteRepository(db_session).create(suite)
    return BenchmarkIngestionService(db_session,clock=lambda:NOW),db_session


def running(service, key="INGEST-1"):
    run=service.create_run(identity(key)); return service.start_run(run.id)


def test_complete_conversation_persists_full_hierarchy(ingestion):
    service,db=ingestion; run=running(service); result=service.ingest_conversation(run.id,conversation())
    assert result.status is IngestionItemStatus.INGESTED
    assert len(BenchmarkProviderTurnRepository(db).list_in_order(result.conversation_result_id))==2
    assert len(BenchmarkToolExecutionRepository(db).list_by_conversation(result.conversation_result_id))==1
    assert len(BenchmarkMetricRepository(db).list_by_conversation(result.conversation_result_id))>=10


def test_identical_retry_is_idempotent(ingestion):
    service,db=ingestion; run=running(service); first=service.ingest_conversation(run.id,conversation()); second=service.ingest_conversation(run.id,conversation())
    assert second.status is IngestionItemStatus.IDEMPOTENT and second.conversation_result_id==first.conversation_result_id
    assert db.scalar(select(func.count()).select_from(BenchmarkConversationResult))==1


def test_conflicting_retry_is_rejected(ingestion):
    service,_=ingestion; run=running(service); service.ingest_conversation(run.id,conversation())
    with pytest.raises(IngestionConflictError): service.ingest_conversation(run.id,conversation(output=3))


def test_batch_preserves_success_and_reports_failed_item(ingestion):
    service,_=ingestion; run=running(service)
    results=service.ingest_batch(run.id,(conversation(),conversation("TC-001",output=4),conversation("TC-002")))
    assert [r.status for r in results]==[IngestionItemStatus.INGESTED,IngestionItemStatus.FAILED,IngestionItemStatus.INGESTED]


def test_ingestion_request_creates_and_starts_run(ingestion):
    service,_=ingestion; result=service.ingest_request(BenchmarkExecutionIngestionRequest(identity=identity("REQUEST-1"),conversations=(conversation(),)))
    assert len(result.items)==1 and BenchmarkRunRepository(service._session).get_by_id(result.benchmark_run_id).status is RunStatus.RUNNING


def test_completed_run_rejects_new_conversation(ingestion):
    service,_=ingestion; run=running(service); service.ingest_batch(run.id,(conversation(),conversation("TC-002"))); service.finalize_run(run.id)
    with pytest.raises(IngestionLifecycleError): service.ingest_conversation(run.id,conversation("TC-003"))


def test_completed_run_accepts_identical_idempotent_retry(ingestion):
    service,_=ingestion; request=BenchmarkExecutionIngestionRequest(identity=identity("TERMINAL-RETRY"),conversations=(conversation(),conversation("TC-002")))
    first=service.ingest_request(request); service.finalize_run(first.benchmark_run_id)
    second=service.ingest_request(request)
    assert all(item.status is IngestionItemStatus.IDEMPOTENT for item in second.items)


def test_partial_finalization(ingestion):
    service,_=ingestion; run=running(service); service.ingest_conversation(run.id,conversation())
    summary=service.finalize_run(run.id); assert summary.finalized_status=="partially_completed" and summary.ingested_conversation_count==1


def test_complete_finalization_and_aggregates(ingestion):
    service,_=ingestion; run=running(service); service.ingest_batch(run.id,(conversation(),conversation("TC-002")))
    summary=service.finalize_run(run.id)
    assert summary.finalized_status=="completed" and summary.total_provider_turns==4 and summary.total_tool_executions==2 and summary.total_tokens==50


def test_empty_finalization_marks_failed(ingestion):
    service,_=ingestion; run=running(service); summary=service.finalize_run(run.id)
    assert summary.finalized_status=="failed"


def test_run_identity_conflict_is_rejected(ingestion):
    service,_=ingestion; service.create_run(identity())
    with pytest.raises(IngestionConflictError): service.create_run(identity().model_copy(update={"model_name":"other"}))


@pytest.mark.parametrize("repository_name", ["_turns","_tools","_metrics","_failures"])
def test_child_failure_rolls_back_entire_conversation(ingestion,monkeypatch,repository_name):
    service,db=ingestion; run=running(service,repository_name)
    monkeypatch.setattr(getattr(service,repository_name),"bulk_insert",lambda records: (_ for _ in ()).throw(RuntimeError("boom")))
    result=service._ingest_safely(run.id,conversation())
    assert result.status is IngestionItemStatus.FAILED
    assert db.scalar(select(func.count()).select_from(BenchmarkConversationResult))==0


def test_status_summary_is_typed(ingestion):
    service,_=ingestion; run=running(service); service.ingest_conversation(run.id,conversation())
    summary=service.get_ingestion_status(run.id); assert summary.conversation_count==1 and summary.provider_turn_count==2


def test_partial_child_state_is_atomically_replaced(ingestion):
    service,db=ingestion; run=running(service); first=service.ingest_conversation(run.id,conversation())
    child=db.scalar(select(BenchmarkProviderTurn).where(BenchmarkProviderTurn.conversation_result_id==first.conversation_result_id).limit(1))
    db.delete(child); db.flush()
    recovered=service.ingest_conversation(run.id,conversation())
    assert recovered.status is IngestionItemStatus.INGESTED
    assert len(BenchmarkProviderTurnRepository(db).list_in_order(recovered.conversation_result_id))==2
