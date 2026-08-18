"""Versioned, evidence-aware model scoring."""
from decimal import Decimal
from app.benchmark_reporting.contracts import (
    MissingMetricBehavior,ModelPerformanceSummary,ScoringPolicy,WeightedScoreComponent,
)
from app.benchmark_reporting.errors import ScoringPolicyError

def score_model(snapshot, metric_summaries, policy:ScoringPolicy):
    scores={item.metric_key:item.normalized_average for item in metric_summaries if item.normalized_average is not None and item.count>=policy.minimum_evidence_count}
    available=tuple(key for key in policy.metric_weights if key in scores and key not in policy.exclusion_rules)
    missing=tuple(key for key in policy.metric_weights if key not in available)
    if missing and policy.missing_metric_behavior is MissingMetricBehavior.REQUIRE_ALL:
        overall=None; components=(); coverage=sum(policy.metric_weights[key] for key in available)
    else:
        coverage=sum((policy.metric_weights[key] for key in available),Decimal("0"))
        components=[]
        for key in available:
            effective=policy.metric_weights[key]/coverage if coverage else Decimal("0")
            components.append(WeightedScoreComponent(dimension=key,score=scores[key],configured_weight=policy.metric_weights[key],effective_weight=effective,weighted_score=scores[key]*effective))
        overall=sum((item.weighted_score for item in components),Decimal("0")) if components else None
        components=tuple(components)
    return ModelPerformanceSummary(benchmark_run_id=snapshot.run.id,run_key=snapshot.run.run_key,
        model_name=snapshot.run.model_name,provider_name=snapshot.run.provider_name,overall_score=overall,
        score_coverage=coverage,available_dimensions=available,missing_dimensions=missing,weighted_components=components)
