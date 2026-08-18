"""Deterministic sanitized Stage 15.3 demonstration artifacts."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.benchmark_analytics.contracts import (
    DeploymentMode, ModelConfigurationSnapshot, PricingSnapshot, ProviderType,
)
from app.benchmark_ingestion.contracts import (
    BenchmarkExecutionIngestionRequest, BenchmarkRunIdentity,
    CompletedConversationExecution, DeterministicEvaluationArtifact,
    ProviderTurnExecution, RuntimeTerminationArtifact, ToolExecutionArtifact,
    UsageArtifact,
)


STAGE_15_3_BACKFILL_RUN_KEY = "stage-15-3-sanitized-demonstration-v1"


def build_stage_15_3_backfill() -> BenchmarkExecutionIngestionRequest:
    """Return sanitized fixture data; it contains no customer transcript or identifier."""
    now = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
    identity = BenchmarkRunIdentity(
        suite_key="stage-15-3-validation", suite_version="1",
        run_key=STAGE_15_3_BACKFILL_RUN_KEY, model_name="qwen3:8b",
        provider_name="ollama", provider_type=ProviderType.LOCAL_RUNTIME,
        deployment_mode=DeploymentMode.LOCAL,
        configuration_snapshot=ModelConfigurationSnapshot(
            context_window_limit=8192, maximum_output_tokens=256,
            prompt_version="production-v1", harness_version="stage-15.3",
        ), pricing_snapshot=PricingSnapshot(),
    )
    conversations = []
    for index, category in enumerate(("orders", "payments"), start=1):
        first = ProviderTurnExecution(
            turn_number=1, finish_reason="tool_calls",
            usage=UsageArtifact(input_tokens=100, output_tokens=10, total_tokens=110),
            latency_ms=Decimal("20"), occurred_at=now,
        )
        second = ProviderTurnExecution(
            turn_number=2, finish_reason="stop",
            usage=UsageArtifact(input_tokens=120, output_tokens=20, total_tokens=140),
            latency_ms=Decimal("25"), occurred_at=now,
        )
        tool = ToolExecutionArtifact(
            execution_order=1, provider_turn_number=1,
            tool_name="list_current_orders" if category == "orders" else "get_payment_status",
            expected_tool="list_current_orders" if category == "orders" else "get_payment_status",
            selection_correct=True, arguments_valid=True, authorization_passed=True,
            execution_successful=True, latency_ms=Decimal("5"),
            arguments={"reference": "ORD-*****25"}, result_summary={"outcome": "success"},
            occurred_at=now,
        )
        conversations.append(CompletedConversationExecution(
            test_case_key=f"S15-3-{index:03d}", language="ar-EG", category=category,
            expected_intent=f"{category}_lookup", actual_intent=f"{category}_lookup",
            customer_turn_count=2, provider_turns=(first, second), tool_executions=(tool,),
            termination=RuntimeTerminationArtifact(
                reason="final_response", runtime_completed=True, task_completed=True,
            ), evaluation=DeterministicEvaluationArtifact(
                grounding_enforced=True, continuity_resolved=True,
                acceptance_criteria_passed=True,
            ), started_at=now, completed_at=now+timedelta(seconds=1),
            trace_metadata={"fixture": "stage_15_3_sanitized"},
        ))
    return BenchmarkExecutionIngestionRequest(identity=identity, conversations=tuple(conversations))
