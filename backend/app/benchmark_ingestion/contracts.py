"""Immutable provider-neutral inputs and results for analytics ingestion."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.benchmark_analytics.contracts import (
    DeploymentMode, FailureCategory, FailureSeverity, ModelConfigurationSnapshot,
    PricingSnapshot, ProviderType, ResponsibilityLayer,
)


class IngestionContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


class IngestionItemStatus(str, Enum):
    INGESTED = "ingested"
    IDEMPOTENT = "idempotent"
    FAILED = "failed"


class BenchmarkRunIdentity(IngestionContract):
    suite_key: str
    suite_version: str
    run_key: str
    model_name: str
    model_version: Optional[str] = None
    provider_name: str
    provider_type: ProviderType
    deployment_mode: DeploymentMode
    configuration_snapshot: ModelConfigurationSnapshot
    pricing_snapshot: PricingSnapshot

    @field_validator("suite_key", "suite_version", "run_key", "model_name", "provider_name")
    @classmethod
    def text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("identity text must not be blank")
        return value


class UsageArtifact(IngestionContract):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @model_validator(mode="after")
    def reconcile(self):
        if min(self.input_tokens, self.output_tokens, self.total_tokens) < 0:
            raise ValueError("usage must be non-negative")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must reconcile")
        return self


class ProviderTurnExecution(IngestionContract):
    turn_number: int
    provider_request_id: Optional[str] = None
    finish_reason: str
    usage: UsageArtifact = Field(default_factory=UsageArtifact)
    latency_ms: Decimal = Decimal("0")
    context_tokens_used: Optional[int] = None
    context_window_limit: Optional[int] = None
    response_valid: bool = True
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = None
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def timestamp(cls, value): return _utc(value)
    @model_validator(mode="after")
    def validate_values(self):
        if self.turn_number < 1 or self.latency_ms < 0:
            raise ValueError("invalid provider turn measurements")
        if self.context_tokens_used is not None and self.context_tokens_used < 0:
            raise ValueError("context usage must be non-negative")
        if self.context_window_limit is not None and self.context_window_limit < 1:
            raise ValueError("context limit must be positive")
        return self


class ToolExecutionArtifact(IngestionContract):
    execution_order: int
    provider_turn_number: Optional[int] = None
    tool_name: str
    expected_tool: Optional[str] = None
    selection_correct: bool
    arguments_valid: bool
    authorization_passed: bool
    execution_successful: bool
    business_failure: bool = False
    failure_code: Optional[str] = None
    latency_ms: Decimal = Decimal("0")
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def timestamp(cls, value): return _utc(value)
    @model_validator(mode="after")
    def validate_values(self):
        if self.execution_order < 1 or self.latency_ms < 0:
            raise ValueError("invalid tool execution measurements")
        return self


class RuntimeTerminationArtifact(IngestionContract):
    reason: str
    runtime_completed: bool
    task_completed: bool
    cancelled: bool = False


class DeterministicFailureSignal(IngestionContract):
    category: FailureCategory
    code: str
    severity: FailureSeverity
    responsibility_layer: ResponsibilityLayer
    description: str
    is_primary: bool = False
    provider_turn_number: Optional[int] = None
    tool_execution_order: Optional[int] = None


class DeterministicEvaluationArtifact(IngestionContract):
    grounding_enforced: Optional[bool] = None
    continuity_resolved: Optional[bool] = None
    hallucination_detected: Optional[bool] = None
    acceptance_criteria_passed: bool
    failures: tuple[DeterministicFailureSignal, ...] = ()


class CompletedConversationExecution(IngestionContract):
    test_case_key: str
    source_conversation_id: Optional[UUID] = None
    language: str
    category: str
    complexity_level: Optional[str] = None
    pressure_level: Optional[str] = None
    expected_intent: str
    actual_intent: Optional[str] = None
    customer_turn_count: int
    clarification_count: int = 0
    provider_turns: tuple[ProviderTurnExecution, ...]
    tool_executions: tuple[ToolExecutionArtifact, ...] = ()
    termination: RuntimeTerminationArtifact
    evaluation: DeterministicEvaluationArtifact
    supplied_usage: Optional[UsageArtifact] = None
    supplied_latency_ms: Optional[Decimal] = None
    started_at: datetime
    completed_at: datetime
    trace_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("started_at", "completed_at")
    @classmethod
    def timestamps(cls, value): return _utc(value)
    @model_validator(mode="after")
    def validate_shape(self):
        if self.customer_turn_count < 1 or self.clarification_count < 0:
            raise ValueError("invalid conversation counts")
        if self.completed_at < self.started_at:
            raise ValueError("completion cannot precede start")
        if tuple(t.turn_number for t in self.provider_turns) != tuple(range(1, len(self.provider_turns)+1)):
            raise ValueError("provider turns must be contiguous and ordered")
        if tuple(t.execution_order for t in self.tool_executions) != tuple(range(1, len(self.tool_executions)+1)):
            raise ValueError("tool executions must be contiguous and ordered")
        return self


class BenchmarkExecutionIngestionRequest(IngestionContract):
    identity: BenchmarkRunIdentity
    conversations: tuple[CompletedConversationExecution, ...]

    @model_validator(mode="after")
    def unique_cases(self):
        keys = [item.test_case_key for item in self.conversations]
        if len(keys) != len(set(keys)):
            raise ValueError("request contains duplicate test-case identities")
        return self


class ConversationIngestionResult(IngestionContract):
    test_case_key: str
    status: IngestionItemStatus
    conversation_result_id: Optional[UUID] = None
    error_code: Optional[str] = None


class IngestionResult(IngestionContract):
    benchmark_run_id: UUID
    items: tuple[ConversationIngestionResult, ...]


class BenchmarkIngestionSummary(IngestionContract):
    benchmark_run_id: UUID
    expected_test_case_count: int
    ingested_conversation_count: int
    benchmark_pass_count: int
    benchmark_fail_count: int
    total_provider_turns: int
    total_tool_executions: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_latency_ms: Decimal
    total_estimated_cost: Optional[Decimal]
    conversations_with_business_data_failures: int
    conversations_with_model_failures: int
    conversations_with_infrastructure_failures: int
    conversations_with_security_failures: int
    finalized_status: str
