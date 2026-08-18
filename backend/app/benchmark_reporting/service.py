"""Read-only reporting application service."""
from datetime import datetime,timezone
from decimal import Decimal
from collections import Counter
from app.benchmark_analytics.contracts import FinalOutcome
from app.benchmark_reporting.aggregation import (
    aggregate_buckets,aggregate_context,aggregate_cost,aggregate_execution,aggregate_failures,
    aggregate_grounding,aggregate_hallucination,aggregate_intent,aggregate_latency,aggregate_reliability,
    aggregate_metrics,aggregate_tokens,aggregate_tools,ratio,segment_summaries,
)
from app.benchmark_reporting.comparison import compare_reports
from app.benchmark_reporting.contracts import (
    BenchmarkRunReport,CategoryPerformanceSummary,ComplexityPerformanceSummary,
    FailureCategorySummary,FailureResponsibilitySummary,LanguagePerformanceSummary,
    OutcomeDistribution,PressurePerformanceSummary,ReportGenerationResult,ReportingDataset,
    RunCompletionSummary,ScoringPolicy,
)
from app.benchmark_reporting.repositories import BenchmarkReportingRepository
from app.benchmark_reporting.scoring import score_model

class BenchmarkReportingService:
    def __init__(self,repository:BenchmarkReportingRepository,*,clock=lambda:datetime.now(timezone.utc)):
        self._repository=repository; self._clock=clock
    def generate_run_report(self,run_id,policy:ScoringPolicy,context_threshold=Decimal(".9")):
        snapshot=self._repository.load_run(run_id); rows=snapshot.conversations; expected=snapshot.suite.test_case_count; stored=len(rows)
        passed=sum(r.passed for r in rows); completed=sum(r.final_outcome is not FinalOutcome.CANCELLED for r in rows); failed=stored-passed
        completion=RunCompletionSummary(expected_test_cases=expected,stored_test_cases=stored,completed_cases=completed,passed_cases=passed,failed_cases=failed,incomplete_cases=max(expected-stored,0),pass_rate=ratio(passed,stored),completion_rate=ratio(stored,expected) or Decimal("0"))
        counts=Counter(r.final_outcome.value for r in rows); outcomes=OutcomeDistribution(counts=dict(sorted(counts.items())),rates={key:ratio(value,stored) for key,value in sorted(counts.items())})
        metrics=aggregate_metrics(snapshot.metrics); performance=score_model(snapshot,metrics,policy)
        return BenchmarkRunReport(suite_key=snapshot.suite.suite_key,suite_version=snapshot.suite.version,suite_content_hash=snapshot.suite.content_hash,run=snapshot.run,completion=completion,execution=aggregate_execution(snapshot),reliability=aggregate_reliability(snapshot),outcomes=outcomes,grounding=aggregate_grounding(snapshot),hallucination=aggregate_hallucination(snapshot),quality_metrics=metrics,languages=segment_summaries(snapshot,"language",LanguagePerformanceSummary),categories=segment_summaries(snapshot,"category",CategoryPerformanceSummary),tools=aggregate_tools(snapshot),failure_categories=aggregate_failures(snapshot,"failure_category",FailureCategorySummary),failure_responsibilities=aggregate_failures(snapshot,"responsibility_layer",FailureResponsibilitySummary),tokens=aggregate_tokens(snapshot),latency=aggregate_latency(snapshot),context=aggregate_context(snapshot,context_threshold),cost=aggregate_cost(snapshot),complexity=segment_summaries(snapshot,"complexity_level",ComplexityPerformanceSummary),pressure=segment_summaries(snapshot,"pressure_level",PressurePerformanceSummary),intent=aggregate_intent(snapshot),customer_turn_buckets=aggregate_buckets(snapshot,"customer_turns"),tool_depth_buckets=aggregate_buckets(snapshot,"tools"),performance=performance,generated_at=self._clock())
    def compare_runs(self,run_ids,policy):
        reports=tuple(self.generate_run_report(run_id,policy) for run_id in run_ids)
        return compare_reports(reports,policy,self._clock())
    def generate_dataset(self,run_ids,policy,compare=True):
        reports=tuple(self.generate_run_report(run_id,policy) for run_id in run_ids)
        comparison=compare_reports(reports,policy,self._clock()) if compare and len(reports)>1 else None
        now=self._clock(); return ReportGenerationResult(dataset=ReportingDataset(run_reports=reports,comparison=comparison),generated_at=now)
