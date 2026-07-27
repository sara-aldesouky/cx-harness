"""Explicit normalized-artifact to analytics-domain mappings."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.benchmark_analytics.contracts import (
    ConversationResultRecord, EvaluationMethod, FailureCategory, FailureEventRecord,
    FailureSeverity, FinalOutcome, MetricResultRecord, ProviderTurnRecord,
    ResponsibilityLayer, ToolExecutionRecord,
)
from app.benchmark_ingestion.contracts import CompletedConversationExecution
from app.benchmark_ingestion.costing import CostCalculation
from app.benchmark_ingestion.errors import IngestionValidationError
from app.benchmark_ingestion.sanitization import sanitize_mapping, sanitize_text


EVALUATOR = "cx_harness_deterministic_ingestion"
EVALUATOR_VERSION = "1.0.0"


def calculate_usage(execution: CompletedConversationExecution) -> tuple[int, int, int]:
    input_tokens = sum(turn.usage.input_tokens for turn in execution.provider_turns)
    output_tokens = sum(turn.usage.output_tokens for turn in execution.provider_turns)
    total = input_tokens + output_tokens
    if execution.supplied_usage and execution.supplied_usage != execution.supplied_usage.model_copy(
        update={"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total}
    ):
        raise IngestionValidationError("supplied usage disagrees with provider turns")
    return input_tokens, output_tokens, total


def calculate_latency(execution: CompletedConversationExecution) -> Decimal:
    measured = sum((turn.latency_ms for turn in execution.provider_turns), Decimal("0"))
    measured += sum((tool.latency_ms for tool in execution.tool_executions), Decimal("0"))
    if execution.supplied_latency_ms is not None and execution.supplied_latency_ms != measured:
        raise IngestionValidationError("supplied latency disagrees with child artifacts")
    return measured


def map_conversation(execution, run_id: UUID, cost: CostCalculation, now: datetime):
    input_tokens, output_tokens, total_tokens = calculate_usage(execution)
    latency = calculate_latency(execution)
    failures = execution.evaluation.failures
    infrastructure = any(f.responsibility_layer in {ResponsibilityLayer.HARNESS, ResponsibilityLayer.PROVIDER, ResponsibilityLayer.EVALUATION_PIPELINE} for f in failures)
    grounding = any(f.category is FailureCategory.GROUNDING for f in failures) or execution.evaluation.grounding_enforced is False
    hallucination = execution.evaluation.hallucination_detected is True
    if execution.termination.cancelled:
        outcome = FinalOutcome.CANCELLED
    elif infrastructure:
        outcome = FinalOutcome.INFRASTRUCTURE_FAILURE
    elif execution.evaluation.acceptance_criteria_passed:
        outcome = FinalOutcome.PASSED
    else:
        outcome = FinalOutcome.FAILED
    primary = next((f.category for f in failures if f.is_primary), failures[0].category if failures else None)
    successful_tools = sum(tool.execution_successful for tool in execution.tool_executions)
    return ConversationResultRecord(
        id=uuid4(), benchmark_run_id=run_id, test_case_key=execution.test_case_key,
        source_conversation_id=execution.source_conversation_id,
        language=execution.language, category=execution.category,
        complexity_level=execution.complexity_level, pressure_level=execution.pressure_level,
        expected_intent=execution.expected_intent, actual_intent=execution.actual_intent,
        final_outcome=outcome, passed=execution.evaluation.acceptance_criteria_passed,
        failure_category=primary, provider_turn_count=len(execution.provider_turns),
        customer_turn_count=execution.customer_turn_count,
        clarification_count=execution.clarification_count,
        tool_execution_count=len(execution.tool_executions),
        successful_tool_execution_count=successful_tools,
        failed_tool_execution_count=len(execution.tool_executions)-successful_tools,
        hallucination_detected=hallucination, grounding_failure_detected=grounding,
        infrastructure_failure_detected=infrastructure, input_tokens=input_tokens,
        output_tokens=output_tokens, total_tokens=total_tokens, total_latency_ms=latency,
        estimated_cost=cost.amount, currency_code=cost.currency_code,
        started_at=execution.started_at, completed_at=execution.completed_at, created_at=now,
    )


def map_turns(execution, conversation_id: UUID):
    records = []
    ids = {}
    for turn in execution.provider_turns:
        record_id = uuid4(); ids[turn.turn_number] = record_id
        ratio = None
        if turn.context_tokens_used is not None and turn.context_window_limit:
            ratio = Decimal(turn.context_tokens_used) / Decimal(turn.context_window_limit)
            ratio = min(ratio, Decimal("1"))
        records.append(ProviderTurnRecord(
            id=record_id, conversation_result_id=conversation_id, turn_number=turn.turn_number,
            provider_request_id=turn.provider_request_id, finish_reason=turn.finish_reason,
            input_tokens=turn.usage.input_tokens, output_tokens=turn.usage.output_tokens,
            total_tokens=turn.usage.total_tokens, latency_ms=turn.latency_ms,
            context_tokens_used=turn.context_tokens_used,
            context_window_limit=turn.context_window_limit,
            context_utilization_ratio=ratio, response_valid=turn.response_valid,
            request_metadata=sanitize_mapping(turn.request_metadata),
            response_metadata=sanitize_mapping(turn.response_metadata),
            error_code=turn.error_code, created_at=turn.occurred_at,
        ))
    return tuple(records), ids


def map_tools(execution, conversation_id: UUID, turn_ids):
    records = []; ids = {}
    for tool in execution.tool_executions:
        if tool.provider_turn_number is not None and tool.provider_turn_number not in turn_ids:
            raise IngestionValidationError("tool references an unknown provider turn")
        record_id = uuid4(); ids[tool.execution_order] = record_id
        records.append(ToolExecutionRecord(
            id=record_id, conversation_result_id=conversation_id,
            provider_turn_id=turn_ids.get(tool.provider_turn_number),
            execution_order=tool.execution_order, tool_name=tool.tool_name,
            expected_tool=tool.expected_tool, selection_correct=tool.selection_correct,
            arguments_valid=tool.arguments_valid,
            authorization_passed=tool.authorization_passed,
            execution_successful=tool.execution_successful,
            business_failure=tool.business_failure, failure_code=tool.failure_code,
            latency_ms=tool.latency_ms, sanitized_arguments=sanitize_mapping(tool.arguments),
            sanitized_result_summary=sanitize_mapping(tool.result_summary), created_at=tool.occurred_at,
        ))
    return tuple(records), ids


def _metric(conversation_id, key, *, numeric=None, boolean=None, normalized=None, evidence=None, now):
    return MetricResultRecord(
        conversation_result_id=conversation_id, metric_key=key, metric_version="1.0.0",
        value_numeric=numeric, value_boolean=boolean, normalized_score=normalized,
        evaluation_method=EvaluationMethod.DETERMINISTIC_RULE, evaluator_name=EVALUATOR,
        evaluator_version=EVALUATOR_VERSION, evidence=sanitize_mapping(evidence or {}), created_at=now,
    )


def map_metrics(execution, conversation, cost: CostCalculation, now):
    tools = execution.tool_executions; turns = execution.provider_turns
    rate = lambda passed, total: Decimal(passed) / Decimal(total) if total else Decimal("1")
    successful = sum(t.execution_successful for t in tools)
    selected = sum(t.selection_correct for t in tools)
    valid_args = sum(t.arguments_valid for t in tools)
    authorized = sum(t.authorization_passed for t in tools)
    valid_responses = sum(t.response_valid for t in turns)
    metrics = [
        _metric(conversation.id, "tool_execution_success_rate", numeric=rate(successful,len(tools)), normalized=rate(successful,len(tools)), now=now),
        _metric(conversation.id, "tool_selection_match_rate", numeric=rate(selected,len(tools)), normalized=rate(selected,len(tools)), now=now),
        _metric(conversation.id, "argument_validation_rate", numeric=rate(valid_args,len(tools)), normalized=rate(valid_args,len(tools)), now=now),
        _metric(conversation.id, "authorization_pass_rate", numeric=rate(authorized,len(tools)), normalized=rate(authorized,len(tools)), now=now),
        _metric(conversation.id, "provider_response_validity_rate", numeric=rate(valid_responses,len(turns)), normalized=rate(valid_responses,len(turns)), now=now),
        _metric(conversation.id, "conversation_completion", boolean=execution.termination.runtime_completed, normalized=Decimal(int(execution.termination.runtime_completed)), now=now),
        _metric(conversation.id, "clarification_count", numeric=Decimal(execution.clarification_count), now=now),
        _metric(conversation.id, "input_token_count", numeric=Decimal(conversation.input_tokens), now=now),
        _metric(conversation.id, "output_token_count", numeric=Decimal(conversation.output_tokens), now=now),
        _metric(conversation.id, "total_token_count", numeric=Decimal(conversation.total_tokens), now=now),
        _metric(conversation.id, "latency_ms", numeric=conversation.total_latency_ms, now=now),
    ]
    if execution.evaluation.grounding_enforced is not None:
        value=execution.evaluation.grounding_enforced; metrics.append(_metric(conversation.id,"grounding_enforcement_rate",boolean=value,normalized=Decimal(int(value)),now=now))
    if execution.evaluation.continuity_resolved is not None:
        value=execution.evaluation.continuity_resolved; metrics.append(_metric(conversation.id,"continuity_resolution_rate",boolean=value,normalized=Decimal(int(value)),now=now))
    ratios = [t.context_utilization_ratio for t in map_turns(execution, conversation.id)[0] if t.context_utilization_ratio is not None]
    if ratios: metrics.append(_metric(conversation.id,"context_utilization_ratio",numeric=max(ratios),normalized=max(ratios),now=now))
    if cost.amount is not None: metrics.append(_metric(conversation.id,"estimated_cost",numeric=cost.amount,evidence=cost.evidence,now=now))
    return tuple(metrics)


def map_failures(execution, conversation_id, turn_ids, tool_ids, now):
    records=[]
    for signal in execution.evaluation.failures:
        if signal.provider_turn_number is not None and signal.provider_turn_number not in turn_ids:
            raise IngestionValidationError("failure references unknown provider turn")
        if signal.tool_execution_order is not None and signal.tool_execution_order not in tool_ids:
            raise IngestionValidationError("failure references unknown tool execution")
        records.append(FailureEventRecord(
            conversation_result_id=conversation_id,
            provider_turn_id=turn_ids.get(signal.provider_turn_number),
            tool_execution_id=tool_ids.get(signal.tool_execution_order),
            failure_category=signal.category, failure_code=signal.code,
            severity=signal.severity, is_primary=signal.is_primary,
            description=sanitize_text(signal.description),
            responsibility_layer=signal.responsibility_layer, created_at=now,
        ))
    return tuple(records)
