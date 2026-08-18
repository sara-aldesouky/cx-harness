"""Compatibility-checked model comparison and contextual winner logic."""
from datetime import datetime,timezone
from decimal import Decimal
from app.benchmark_reporting.contracts import (
    ComparisonWinner,MetricComparisonRow,ModelComparisonReport,WinnerDirection,
)
from app.benchmark_reporting.errors import IncompatibleComparisonError

def compare_reports(reports,policy,generated_at=None):
    if len(reports)<2: raise IncompatibleComparisonError("at least two benchmark runs are required")
    first=reports[0]; identity=(first.suite_key,first.suite_version,first.suite_content_hash,first.completion.expected_test_cases)
    if any((r.suite_key,r.suite_version,r.suite_content_hash,r.completion.expected_test_cases)!=identity for r in reports[1:]):
        raise IncompatibleComparisonError("benchmark suite identity is incompatible")
    metric_versions=[{(m.metric_key,m.metric_version,m.evaluation_method,m.evaluator_name,m.evaluator_version) for m in r.quality_metrics} for r in reports]
    if any(value!=metric_versions[0] for value in metric_versions[1:]): raise IncompatibleComparisonError("metric definitions are incompatible")
    def metric(report,key): return next((m.normalized_average for m in report.quality_metrics if m.metric_key==key),None)
    def segment(report,collection,label,field):
        item=next((x for x in collection if x.segment==label),None); return getattr(item,field) if item else None
    dimensions={
        "overall_quality":({r.run.run_key:r.performance.overall_score for r in reports},WinnerDirection.HIGHER),
        "pass_rate":({r.run.run_key:r.completion.pass_rate for r in reports},WinnerDirection.HIGHER),
        "task_completion":({r.run.run_key:metric(r,"conversation_completion") for r in reports},WinnerDirection.HIGHER),
        "tool_selection":({r.run.run_key:metric(r,"tool_selection_match_rate") for r in reports},WinnerDirection.HIGHER),
        "lowest_latency":({r.run.run_key:r.latency.average_conversation_latency_ms for r in reports},WinnerDirection.LOWER),
        "lowest_hallucination":({r.run.run_key:r.hallucination.hallucination_rate for r in reports},WinnerDirection.LOWER),
        "egyptian_arabic":({r.run.run_key:segment(r,r.languages,"ar-EG","pass_rate") for r in reports},WinnerDirection.HIGHER),
        "franco_arabic":({r.run.run_key:segment(r,r.languages,"franco","pass_rate") for r in reports},WinnerDirection.HIGHER),
        "high_complexity":({r.run.run_key:segment(r,r.complexity,"high","pass_rate") for r in reports},WinnerDirection.HIGHER),
        "lowest_cost":({r.run.run_key:r.cost.total_estimated_cost for r in reports},WinnerDirection.LOWER),
        "quality_to_cost":({r.run.run_key:(r.performance.overall_score/r.cost.total_estimated_cost if r.performance.overall_score is not None and r.cost.total_estimated_cost not in {None,Decimal("0")} else None) for r in reports},WinnerDirection.HIGHER),
    }
    rows=[]; winners=[]
    currencies={r.cost.currency_code for r in reports if r.cost.available}
    cost_comparable=len(currencies)==1 and all(r.cost.available for r in reports)
    for name,(values,direction) in dimensions.items():
        comparable=all(v is not None for v in values.values()) and (name not in {"lowest_cost","quality_to_cost"} or cost_comparable)
        reason=None if comparable else "evidence unavailable or incompatible"
        rows.append(MetricComparisonRow(dimension=name,values_by_run=values,comparable=comparable,reason=reason))
        winners.append(select_winner(name,values,direction,comparable))
    return ModelComparisonReport(suite_key=identity[0],suite_version=identity[1],suite_content_hash=identity[2],scoring_policy_key=policy.policy_key,scoring_policy_version=policy.policy_version,runs=tuple(reports),metric_rows=tuple(rows),winners=tuple(winners),cost_ranking_available=cost_comparable,generated_at=generated_at or datetime.now(timezone.utc))

def select_winner(dimension,values,direction,eligible=True):
    available={k:v for k,v in values.items() if v is not None}
    conditions=("compatible benchmark identity","compatible metric evidence")
    if not eligible or not available:return ComparisonWinner(dimension=dimension,available=False,eligibility_conditions=conditions,explanation="Winner unavailable because evidence is missing or incompatible.")
    ordered=sorted(available.items(),key=lambda x:x[1],reverse=direction is WinnerDirection.HIGHER)
    winner=ordered[0]; runner=ordered[1] if len(ordered)>1 else None; tie=runner is not None and winner[1]==runner[1]
    return ComparisonWinner(dimension=dimension,available=True,winning_run_key=winner[0],value=winner[1],runner_up_run_key=runner[0] if runner else None,difference=abs(winner[1]-runner[1]) if runner else None,tie=tie,eligibility_conditions=conditions,explanation="Tie on this dimension." if tie else "Winner selected only for this compatible reporting dimension.")
