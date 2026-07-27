"""Immutable provider-neutral benchmark reporting datasets."""

from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.benchmark_analytics.contracts import (
    BenchmarkRunDefinition, BenchmarkSuiteDefinition, ConversationResultRecord,
    FailureEventRecord, MetricResultRecord, ProviderTurnRecord, ToolExecutionRecord,
)

class ReportContract(BaseModel):
    model_config=ConfigDict(frozen=True,extra="forbid")

def _rate(value):
    if value is not None and not Decimal("0") <= value <= Decimal("1"): raise ValueError("rate must be between zero and one")
    return value

class MissingMetricBehavior(str,Enum):
    EXCLUDE_AND_RENORMALIZE="exclude_and_renormalize"
    REQUIRE_ALL="require_all"

class WinnerDirection(str,Enum):
    HIGHER="higher"
    LOWER="lower"

class RunAnalyticsSnapshot(ReportContract):
    suite: BenchmarkSuiteDefinition
    run: BenchmarkRunDefinition
    conversations: tuple[ConversationResultRecord,...]
    provider_turns: tuple[ProviderTurnRecord,...]
    tool_executions: tuple[ToolExecutionRecord,...]
    metrics: tuple[MetricResultRecord,...]
    failures: tuple[FailureEventRecord,...]

class RunCompletionSummary(ReportContract):
    expected_test_cases:int; stored_test_cases:int; completed_cases:int; passed_cases:int
    failed_cases:int; incomplete_cases:int; pass_rate:Optional[Decimal]; completion_rate:Decimal
    _rates=field_validator("pass_rate","completion_rate")(_rate)

class OutcomeDistribution(ReportContract):
    counts:dict[str,int]; rates:dict[str,Decimal]

class RunExecutionSummary(ReportContract):
    total_provider_turns:int; average_provider_turns:Optional[Decimal]
    total_tool_executions:int; successful_tool_executions:int; failed_tool_executions:int
    tool_execution_success_rate:Optional[Decimal]; total_clarifications:int
    average_clarifications:Optional[Decimal]

class ReliabilitySummary(ReportContract):
    conversations_with_model_failures:int; conversations_with_business_data_failures:int
    conversations_with_provider_failures:int; conversations_with_harness_failures:int
    conversations_with_infrastructure_failures:int; conversations_with_security_failures:int
    conversations_with_evaluation_pipeline_failures:int

class GroundingSummary(ReportContract):
    evaluated_conversations:int; enforcement_pass_count:int; enforcement_failure_count:int
    grounding_pass_rate:Optional[Decimal]; grounding_failure_rate:Optional[Decimal]
class HallucinationSummary(ReportContract):
    conversations_with_stored_signal:int; hallucination_rate:Optional[Decimal]

class ConversationBucketSummary(ReportContract):
    bucket:str; conversation_count:int; pass_rate:Decimal; grounding_pass_rate:Decimal
    context_retention_rate:Optional[Decimal]; average_tokens:Decimal; average_latency_ms:Decimal
    hallucination_rate:Decimal; model_failure_rate:Decimal

class QualityMetricSummary(ReportContract):
    metric_key:str; metric_version:str; evaluation_method:str; evaluator_name:str; evaluator_version:str
    count:int; mean:Optional[Decimal]=None; median:Optional[Decimal]=None
    minimum:Optional[Decimal]=None; maximum:Optional[Decimal]=None; standard_deviation:Optional[Decimal]=None
    normalized_average:Optional[Decimal]=None; true_count:Optional[int]=None; false_count:Optional[int]=None
    true_rate:Optional[Decimal]=None; value_distribution:dict[str,int]=Field(default_factory=dict)

class SegmentPerformanceSummary(ReportContract):
    segment:str; case_count:int; pass_rate:Decimal; task_completion_rate:Optional[Decimal]
    tool_selection_accuracy:Optional[Decimal]; tool_success_rate:Optional[Decimal]
    grounding_failure_rate:Decimal; hallucination_rate:Decimal; clarification_rate:Decimal
    average_provider_turns:Decimal; average_tool_calls:Decimal; average_total_tokens:Decimal
    average_latency_ms:Decimal; average_estimated_cost:Optional[Decimal]
    model_failure_rate:Decimal; business_data_failure_rate:Decimal; context_loss_rate:Decimal

class LanguagePerformanceSummary(SegmentPerformanceSummary): pass
class CategoryPerformanceSummary(SegmentPerformanceSummary): pass
class ComplexityPerformanceSummary(SegmentPerformanceSummary): pass
class PressurePerformanceSummary(SegmentPerformanceSummary): pass

class ToolPerformanceSummary(ReportContract):
    tool_name:str; expected_count:int; selected_count:int; correct_selection_count:int
    incorrect_selection_count:int; selection_precision:Optional[Decimal]; selection_recall:Optional[Decimal]
    execution_attempts:int; valid_argument_count:int; invalid_argument_count:int
    authorization_pass_count:int; successful_execution_count:int; business_failure_count:int
    runtime_failure_count:int; average_latency_ms:Optional[Decimal]; median_latency_ms:Optional[Decimal]
    failure_code_distribution:dict[str,int]

class FailureCategorySummary(ReportContract):
    category:str; event_count:int; affected_conversation_count:int; affected_conversation_rate:Decimal
class FailureResponsibilitySummary(ReportContract):
    responsibility_layer:str; event_count:int; affected_conversation_count:int; affected_conversation_rate:Decimal

class TokenUsageSummary(ReportContract):
    total_input_tokens:int; total_output_tokens:int; total_tokens:int
    average_tokens_per_conversation:Optional[Decimal]; median_tokens_per_conversation:Optional[Decimal]
    minimum_tokens:Optional[int]; maximum_tokens:Optional[int]; standard_deviation:Optional[Decimal]
    input_to_output_ratio:Optional[Decimal]; tokens_per_successful_conversation:Optional[Decimal]
    tokens_per_passed_case:Optional[Decimal]

class LatencySummary(ReportContract):
    wall_clock_duration_ms:Optional[Decimal]; accumulated_provider_latency_ms:Decimal
    accumulated_tool_latency_ms:Decimal; accumulated_conversation_latency_ms:Decimal
    average_conversation_latency_ms:Optional[Decimal]; median_conversation_latency_ms:Optional[Decimal]
    minimum_conversation_latency_ms:Optional[Decimal]; maximum_conversation_latency_ms:Optional[Decimal]
    standard_deviation_ms:Optional[Decimal]; p50_ms:Optional[Decimal]; p75_ms:Optional[Decimal]
    p90_ms:Optional[Decimal]; p95_ms:Optional[Decimal]; p99_ms:Optional[Decimal]
    average_provider_turn_latency_ms:Optional[Decimal]; average_tool_latency_ms:Optional[Decimal]

class ContextBucketSummary(ReportContract):
    bucket:str; conversation_count:int; pass_rate:Decimal; average_latency_ms:Decimal
    average_output_tokens:Decimal; model_failure_rate:Decimal; context_loss_rate:Decimal
class ContextWindowSummary(ReportContract):
    total_context_tokens:Optional[int]; average_context_tokens_per_turn:Optional[Decimal]
    maximum_context_tokens:Optional[int]; average_utilization_ratio:Optional[Decimal]
    maximum_utilization_ratio:Optional[Decimal]; conversations_above_threshold:int
    threshold:Decimal; buckets:tuple[ContextBucketSummary,...]

class CostSummary(ReportContract):
    available:bool; currency_code:Optional[str]; total_estimated_cost:Optional[Decimal]
    average_cost_per_conversation:Optional[Decimal]; median_cost:Optional[Decimal]
    minimum_cost:Optional[Decimal]; maximum_cost:Optional[Decimal]
    cost_per_passed_conversation:Optional[Decimal]; cost_per_completed_task:Optional[Decimal]
    projected_cost_per_thousand_conversations:Optional[Decimal]
    input_token_cost_contribution:Optional[Decimal]; output_token_cost_contribution:Optional[Decimal]
    request_charge_contribution:Optional[Decimal]; missing_components:tuple[str,...]=()

class IntentConfusionRow(ReportContract):
    expected_intent:str; actual_intent:Optional[str]; count:int
class IntentAnalysisSummary(ReportContract):
    evaluated_count:int; exact_match_count:int; exact_match_accuracy:Optional[Decimal]
    missed_intent_count:int; unsupported_intent_count:int; per_intent_accuracy:dict[str,Decimal]
    confusion:tuple[IntentConfusionRow,...]

class ScoringPolicy(ReportContract):
    policy_key:str; policy_version:str; metric_weights:dict[str,Decimal]
    missing_metric_behavior:MissingMetricBehavior=MissingMetricBehavior.EXCLUDE_AND_RENORMALIZE
    minimum_evidence_count:int=1; normalization_rules:dict[str,str]=Field(default_factory=dict)
    exclusion_rules:tuple[str,...]=()
    @model_validator(mode="after")
    def weights(self):
        if not self.metric_weights or sum(self.metric_weights.values(),Decimal("0")) != Decimal("1"): raise ValueError("metric weights must total one")
        if any(value <= 0 for value in self.metric_weights.values()): raise ValueError("metric weights must be positive")
        if self.minimum_evidence_count < 1: raise ValueError("minimum evidence must be positive")
        return self

class WeightedScoreComponent(ReportContract):
    dimension:str; score:Decimal; configured_weight:Decimal; effective_weight:Decimal; weighted_score:Decimal
class ModelPerformanceSummary(ReportContract):
    benchmark_run_id:UUID; run_key:str; model_name:str; provider_name:str
    overall_score:Optional[Decimal]; score_coverage:Decimal
    available_dimensions:tuple[str,...]; missing_dimensions:tuple[str,...]
    weighted_components:tuple[WeightedScoreComponent,...]

class BenchmarkRunReport(ReportContract):
    suite_key:str; suite_version:str; suite_content_hash:str; run:BenchmarkRunDefinition
    completion:RunCompletionSummary; execution:RunExecutionSummary; reliability:ReliabilitySummary
    outcomes:OutcomeDistribution; grounding:GroundingSummary; hallucination:HallucinationSummary
    quality_metrics:tuple[QualityMetricSummary,...]
    languages:tuple[LanguagePerformanceSummary,...]; categories:tuple[CategoryPerformanceSummary,...]
    tools:tuple[ToolPerformanceSummary,...]
    failure_categories:tuple[FailureCategorySummary,...]
    failure_responsibilities:tuple[FailureResponsibilitySummary,...]
    tokens:TokenUsageSummary; latency:LatencySummary; context:ContextWindowSummary; cost:CostSummary
    complexity:tuple[ComplexityPerformanceSummary,...]; pressure:tuple[PressurePerformanceSummary,...]
    intent:IntentAnalysisSummary; customer_turn_buckets:tuple[ConversationBucketSummary,...]
    tool_depth_buckets:tuple[ConversationBucketSummary,...]
    performance:ModelPerformanceSummary; generated_at:datetime
    @field_validator("generated_at")
    @classmethod
    def utc(cls,value):
        if value.tzinfo is None: raise ValueError("generated_at must be timezone-aware")
        return value.astimezone(timezone.utc)

class MetricComparisonRow(ReportContract):
    dimension:str; values_by_run:dict[str,Optional[Decimal]]; comparable:bool; reason:Optional[str]=None
class ComparisonWinner(ReportContract):
    dimension:str; available:bool; winning_run_key:Optional[str]=None; value:Optional[Decimal]=None
    runner_up_run_key:Optional[str]=None; difference:Optional[Decimal]=None; tie:bool=False
    eligibility_conditions:tuple[str,...]=(); explanation:str
class ModelComparisonReport(ReportContract):
    suite_key:str; suite_version:str; suite_content_hash:str; scoring_policy_key:str
    scoring_policy_version:str; runs:tuple[BenchmarkRunReport,...]
    metric_rows:tuple[MetricComparisonRow,...]; winners:tuple[ComparisonWinner,...]
    cost_ranking_available:bool; generated_at:datetime
class ReportingDataset(ReportContract):
    run_reports:tuple[BenchmarkRunReport,...]; comparison:Optional[ModelComparisonReport]=None
class ReportGenerationResult(ReportContract):
    dataset:ReportingDataset; generated_at:datetime
