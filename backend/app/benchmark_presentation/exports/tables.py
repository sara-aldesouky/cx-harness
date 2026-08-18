"""Shared, calculation-free table mapping for CSV and Excel."""

from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Mapping
from uuid import UUID

from pydantic import BaseModel


def scalar(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        import json
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return value


def model_rows(models: Iterable[BaseModel]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: scalar(value) for key, value in model.model_dump(mode="python").items()}
        for model in models
    )


def key_value_rows(model: BaseModel) -> tuple[dict[str, Any], ...]:
    return tuple(
        {"metric": key, "value": scalar(value)}
        for key, value in model.model_dump(mode="python").items()
    )


def run_tables(report) -> tuple[tuple[str, tuple[dict[str, Any], ...]], ...]:
    failures = model_rows(report.failure_categories) + model_rows(report.failure_responsibilities)
    metadata = (
        {"field": "suite_key", "value": report.suite_key},
        {"field": "suite_version", "value": report.suite_version},
        {"field": "suite_content_hash", "value": report.suite_content_hash},
        {"field": "run_key", "value": report.run.run_key},
        {"field": "generated_at", "value": scalar(report.generated_at)},
    )
    intent = model_rows(report.intent.confusion)
    return (
        ("Executive Summary", key_value_rows(report.performance)),
        ("Run Completion", key_value_rows(report.completion)),
        ("Quality Metrics", model_rows(report.quality_metrics)),
        ("Language Breakdown", model_rows(report.languages)),
        ("Category Breakdown", model_rows(report.categories)),
        ("Complexity Breakdown", model_rows(report.complexity)),
        ("Pressure Breakdown", model_rows(report.pressure)),
        ("Tool Performance", model_rows(report.tools)),
        ("Failures", failures),
        ("Intent Analysis", intent or key_value_rows(report.intent)),
        ("Tokens", key_value_rows(report.tokens)),
        ("Latency", key_value_rows(report.latency)),
        ("Context", key_value_rows(report.context)),
        ("Cost", key_value_rows(report.cost)),
        ("Scoring", model_rows(report.performance.weighted_components)),
        ("Metadata", metadata),
    )


def comparison_tables(report) -> tuple[tuple[str, tuple[dict[str, Any], ...]], ...]:
    overview = tuple(
        {
            "run_key": run.run.run_key,
            "model_name": run.run.model_name,
            "provider_name": run.run.provider_name,
            "overall_score": scalar(run.performance.overall_score),
            "score_coverage": scalar(run.performance.score_coverage),
            "pass_rate": scalar(run.completion.pass_rate),
        }
        for run in report.runs
    )
    metadata = (
        {"field": "suite_key", "value": report.suite_key},
        {"field": "suite_version", "value": report.suite_version},
        {"field": "suite_content_hash", "value": report.suite_content_hash},
        {"field": "scoring_policy_key", "value": report.scoring_policy_key},
        {"field": "scoring_policy_version", "value": report.scoring_policy_version},
        {"field": "generated_at", "value": scalar(report.generated_at)},
    )
    score_components = tuple(
        {"run_key": run.run.run_key, **row}
        for run in report.runs
        for row in model_rows(run.performance.weighted_components)
    )
    return (
        ("Executive Summary", overview),
        ("Model Overview", overview),
        ("Metric Comparison", model_rows(report.metric_rows)),
        ("Winner Analysis", model_rows(report.winners)),
        ("Quality", tuple({"run_key": r.run.run_key, **x} for r in report.runs for x in model_rows(r.quality_metrics))),
        ("Languages", tuple({"run_key": r.run.run_key, **x} for r in report.runs for x in model_rows(r.languages))),
        ("Tools", tuple({"run_key": r.run.run_key, **x} for r in report.runs for x in model_rows(r.tools))),
        ("Failures", tuple({"run_key": r.run.run_key, **x} for r in report.runs for x in model_rows(r.failure_categories))),
        ("Latency", tuple({"run_key": r.run.run_key, **x} for r in report.runs for x in key_value_rows(r.latency))),
        ("Cost", tuple({"run_key": r.run.run_key, **x} for r in report.runs for x in key_value_rows(r.cost))),
        ("Score Components", score_components),
        ("Compatibility", model_rows(report.metric_rows)),
        ("Metadata", metadata),
    )
