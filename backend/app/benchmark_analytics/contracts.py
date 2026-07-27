"""Immutable provider-neutral contracts for benchmark analytics."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SuiteStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    FROZEN = "frozen"
    ARCHIVED = "archived"


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationMethod(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    AUTOMATED_EVALUATOR = "automated_evaluator"
    MODEL_JUDGED = "model_judged"
    HUMAN_REVIEW = "human_review"
    IMPORTED_ANNOTATION = "imported_annotation"


class FailureCategory(str, Enum):
    MODEL_REASONING = "model_reasoning"
    INTENT_UNDERSTANDING = "intent_understanding"
    WRONG_TOOL_SELECTION = "wrong_tool_selection"
    INVALID_ARGUMENTS = "invalid_arguments"
    CLARIFICATION_QUALITY = "clarification_quality"
    HALLUCINATION = "hallucination"
    GROUNDING = "grounding"
    LANGUAGE_QUALITY = "language_quality"
    CONTEXT_LOSS = "context_loss"
    BUSINESS_DATA = "business_data"
    PROVIDER_FAILURE = "provider_failure"
    AUTHORIZATION = "authorization"
    SECURITY = "security"
    RUNTIME = "runtime"
    INFRASTRUCTURE = "infrastructure"
    EVALUATION_ERROR = "evaluation_error"
    UNKNOWN = "unknown"


class ResponsibilityLayer(str, Enum):
    MODEL = "model"
    PROVIDER = "provider"
    BUSINESS_CAPABILITY = "business_capability"
    BUSINESS_DATA = "business_data"
    HARNESS = "harness"
    SECURITY = "security"
    EVALUATION_PIPELINE = "evaluation_pipeline"
    UNKNOWN = "unknown"


class FailureSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DeploymentMode(str, Enum):
    LOCAL = "local"
    SELF_HOSTED = "self_hosted"
    MANAGED_API = "managed_api"
    HYBRID = "hybrid"


class ProviderType(str, Enum):
    LOCAL_RUNTIME = "local_runtime"
    API = "api"
    SELF_HOSTED = "self_hosted"


class FinalOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    DEGRADED = "degraded"
    CANCELLED = "cancelled"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


class AnalyticsContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def _text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("text must not be blank")
    return normalized


_SENSITIVE_KEYS = re.compile(
    r"(?:password|secret|token|api[_-]?key|credential|phone|email|address|customer_id)",
    re.I,
)
_RAW_ORDER = re.compile(r"\b(?:ORD-\d+|CX-[A-Z0-9]+(?:-[A-Z0-9]+)+)\b", re.I)


def validate_sanitized_json(value: Mapping[str, Any]) -> dict[str, Any]:
    """Reject secrets, PII keys, and unmasked public order references."""

    def inspect(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if _SENSITIVE_KEYS.search(str(key)):
                    raise ValueError("metadata contains a prohibited sensitive field")
                inspect(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                inspect(nested)
        elif isinstance(item, str) and _RAW_ORDER.search(item) and "*" not in item:
            raise ValueError("metadata contains an unredacted business identifier")

    copied = dict(value)
    inspect(copied)
    return copied


class ModelConfigurationSnapshot(AnalyticsContract):
    temperature: Optional[Decimal] = None
    top_p: Optional[Decimal] = None
    maximum_output_tokens: Optional[int] = None
    context_window_limit: Optional[int] = None
    tool_loop_limit: Optional[int] = None
    timeout_seconds: Optional[Decimal] = None
    prompt_version: Optional[str] = None
    harness_version: Optional[str] = None
    provider_settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_settings")
    @classmethod
    def sanitize_settings(cls, value):
        return validate_sanitized_json(value)

    @model_validator(mode="after")
    def validate_numbers(self):
        if self.temperature is not None and not Decimal("0") <= self.temperature <= Decimal("2"):
            raise ValueError("temperature must be between zero and two")
        if self.top_p is not None and not Decimal("0") <= self.top_p <= Decimal("1"):
            raise ValueError("top_p must be between zero and one")
        for value in (self.maximum_output_tokens, self.context_window_limit, self.tool_loop_limit):
            if value is not None and (isinstance(value, bool) or value < 1):
                raise ValueError("configuration limits must be positive")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        return self


class PricingSnapshot(AnalyticsContract):
    currency_code: str = "USD"
    input_cost_per_million_tokens: Optional[Decimal] = None
    output_cost_per_million_tokens: Optional[Decimal] = None
    request_cost: Optional[Decimal] = None
    hardware_hourly_cost: Optional[Decimal] = None
    electricity_cost_per_kwh: Optional[Decimal] = None
    hosting_overhead: Optional[Decimal] = None
    assumptions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency_code")
    @classmethod
    def currency(cls, value):
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency_code must be a three-letter code")
        return normalized

    @field_validator("assumptions")
    @classmethod
    def sanitize_assumptions(cls, value):
        return validate_sanitized_json(value)

    @model_validator(mode="after")
    def non_negative(self):
        for name in (
            "input_cost_per_million_tokens", "output_cost_per_million_tokens",
            "request_cost", "hardware_hourly_cost", "electricity_cost_per_kwh",
            "hosting_overhead",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError("pricing values must be non-negative")
        return self


class BenchmarkSuiteDefinition(AnalyticsContract):
    id: UUID = Field(default_factory=uuid4)
    suite_key: str
    name: str
    description: str
    version: str
    test_case_count: int
    content_hash: str
    status: SuiteStatus = SuiteStatus.DRAFT
    created_at: datetime
    updated_at: datetime

    @field_validator("suite_key", "name", "description", "version", "content_hash")
    @classmethod
    def normalize_text(cls, value): return _text(value)
    @field_validator("suite_key")
    @classmethod
    def normalize_key(cls, value): return value.lower()
    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps(cls, value): return _utc(value)
    @model_validator(mode="after")
    def shape(self):
        if self.test_case_count < 1 or self.updated_at < self.created_at:
            raise ValueError("invalid suite lifecycle")
        return self


class BenchmarkRunDefinition(AnalyticsContract):
    id: UUID = Field(default_factory=uuid4)
    run_key: str
    benchmark_suite_id: UUID
    model_name: str
    model_version: Optional[str] = None
    provider_name: str
    provider_type: ProviderType
    deployment_mode: DeploymentMode
    configuration_snapshot: ModelConfigurationSnapshot
    pricing_snapshot: PricingSnapshot
    status: RunStatus = RunStatus.CREATED
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("run_key", "model_name", "provider_name")
    @classmethod
    def normalize_text(cls, value): return _text(value)
    @field_validator("model_version")
    @classmethod
    def optional_text(cls, value): return None if value is None else _text(value)
    @field_validator("started_at", "completed_at", "created_at", "updated_at")
    @classmethod
    def timestamps(cls, value): return None if value is None else _utc(value)
    @model_validator(mode="after")
    def lifecycle(self):
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.completed_at is not None and self.started_at is None:
            raise ValueError("completed runs require a start timestamp")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        return self


class ConversationResultRecord(AnalyticsContract):
    id: UUID = Field(default_factory=uuid4)
    benchmark_run_id: UUID
    test_case_key: str
    source_conversation_id: Optional[UUID] = None
    language: str
    category: str
    complexity_level: Optional[str] = None
    pressure_level: Optional[str] = None
    expected_intent: str
    actual_intent: Optional[str] = None
    final_outcome: FinalOutcome
    passed: bool
    failure_category: Optional[FailureCategory] = None
    provider_turn_count: int = 0
    customer_turn_count: int = 0
    clarification_count: int = 0
    tool_execution_count: int = 0
    successful_tool_execution_count: int = 0
    failed_tool_execution_count: int = 0
    hallucination_detected: bool = False
    grounding_failure_detected: bool = False
    infrastructure_failure_detected: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: Decimal = Decimal("0")
    estimated_cost: Optional[Decimal] = None
    currency_code: Optional[str] = None
    started_at: datetime
    completed_at: datetime
    created_at: datetime

    @field_validator("test_case_key", "language", "category", "expected_intent")
    @classmethod
    def text(cls, value): return _text(value)
    @field_validator("started_at", "completed_at", "created_at")
    @classmethod
    def timestamps(cls, value): return _utc(value)
    @field_validator("currency_code")
    @classmethod
    def currency(cls, value):
        if value is None: return None
        value = value.strip().upper()
        if len(value) != 3: raise ValueError("currency code must have three letters")
        return value
    @model_validator(mode="after")
    def totals(self):
        counts = (self.provider_turn_count, self.customer_turn_count, self.clarification_count,
                  self.tool_execution_count, self.successful_tool_execution_count,
                  self.failed_tool_execution_count, self.input_tokens, self.output_tokens,
                  self.total_tokens)
        if any(value < 0 for value in counts) or self.total_latency_ms < 0:
            raise ValueError("counts and latency must be non-negative")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input plus output tokens")
        if self.tool_execution_count != self.successful_tool_execution_count + self.failed_tool_execution_count:
            raise ValueError("tool counts must reconcile")
        if self.estimated_cost is not None and self.estimated_cost < 0:
            raise ValueError("estimated cost must be non-negative")
        if (self.estimated_cost is None) != (self.currency_code is None):
            raise ValueError("cost and currency must be supplied together")
        if self.completed_at < self.started_at:
            raise ValueError("completion cannot precede start")
        return self


class ProviderTurnRecord(AnalyticsContract):
    id: UUID = Field(default_factory=uuid4)
    conversation_result_id: UUID
    turn_number: int
    provider_request_id: Optional[str] = None
    finish_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: Decimal = Decimal("0")
    context_tokens_used: Optional[int] = None
    context_window_limit: Optional[int] = None
    context_utilization_ratio: Optional[Decimal] = None
    response_valid: bool = True
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = None
    created_at: datetime

    @field_validator("finish_reason")
    @classmethod
    def text(cls, value): return _text(value)
    @field_validator("created_at")
    @classmethod
    def timestamp(cls, value): return _utc(value)
    @field_validator("request_metadata", "response_metadata")
    @classmethod
    def sanitized(cls, value): return validate_sanitized_json(value)
    @model_validator(mode="after")
    def validate_counts(self):
        if self.turn_number < 1 or min(self.input_tokens, self.output_tokens, self.total_tokens) < 0 or self.latency_ms < 0:
            raise ValueError("turn values must be non-negative and ordered")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("turn token totals must reconcile")
        if self.context_utilization_ratio is not None and not Decimal("0") <= self.context_utilization_ratio <= Decimal("1"):
            raise ValueError("context utilization must be between zero and one")
        return self


class ToolExecutionRecord(AnalyticsContract):
    id: UUID = Field(default_factory=uuid4)
    conversation_result_id: UUID
    provider_turn_id: Optional[UUID] = None
    execution_order: int
    tool_name: str
    expected_tool: Optional[str] = None
    selection_correct: bool
    arguments_valid: bool
    authorization_passed: bool
    execution_successful: bool
    business_failure: bool = False
    failure_code: Optional[str] = None
    latency_ms: Decimal = Decimal("0")
    sanitized_arguments: dict[str, Any] = Field(default_factory=dict)
    sanitized_result_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("tool_name")
    @classmethod
    def text(cls, value): return _text(value)
    @field_validator("sanitized_arguments", "sanitized_result_summary")
    @classmethod
    def sanitized(cls, value): return validate_sanitized_json(value)
    @field_validator("created_at")
    @classmethod
    def timestamp(cls, value): return _utc(value)
    @model_validator(mode="after")
    def validate_execution(self):
        if self.execution_order < 1 or self.latency_ms < 0:
            raise ValueError("execution order must be positive and latency non-negative")
        if self.execution_successful and self.failure_code is not None:
            raise ValueError("successful executions cannot contain failure codes")
        return self


class MetricResultRecord(AnalyticsContract):
    id: UUID = Field(default_factory=uuid4)
    conversation_result_id: UUID
    metric_key: str
    metric_version: str
    value_numeric: Optional[Decimal] = None
    value_boolean: Optional[bool] = None
    value_text: Optional[str] = None
    maximum_value: Optional[Decimal] = None
    normalized_score: Optional[Decimal] = None
    evaluation_method: EvaluationMethod
    evaluator_name: str
    evaluator_version: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("metric_key", "metric_version", "evaluator_name", "evaluator_version")
    @classmethod
    def text(cls, value): return _text(value)
    @field_validator("evidence")
    @classmethod
    def sanitized(cls, value): return validate_sanitized_json(value)
    @field_validator("created_at")
    @classmethod
    def timestamp(cls, value): return _utc(value)
    @model_validator(mode="after")
    def one_value(self):
        populated = sum(value is not None for value in (self.value_numeric, self.value_boolean, self.value_text))
        if populated != 1:
            raise ValueError("exactly one metric value must be populated")
        if self.maximum_value is not None and self.maximum_value <= 0:
            raise ValueError("maximum_value must be positive")
        if self.normalized_score is not None and not Decimal("0") <= self.normalized_score <= Decimal("1"):
            raise ValueError("normalized score must be between zero and one")
        return self


class FailureEventRecord(AnalyticsContract):
    id: UUID = Field(default_factory=uuid4)
    conversation_result_id: UUID
    provider_turn_id: Optional[UUID] = None
    tool_execution_id: Optional[UUID] = None
    failure_category: FailureCategory
    failure_code: str
    severity: FailureSeverity
    is_primary: bool
    description: str
    responsibility_layer: ResponsibilityLayer
    created_at: datetime

    @field_validator("failure_code", "description")
    @classmethod
    def text(cls, value): return _text(value)
    @field_validator("created_at")
    @classmethod
    def timestamp(cls, value): return _utc(value)


class BenchmarkRunSummary(AnalyticsContract):
    benchmark_run_id: UUID
    conversation_count: int
    passed_count: int
    failed_count: int
    degraded_count: int
    provider_turn_count: int
    tool_execution_count: int
    successful_tool_execution_count: int
    input_tokens: int
    output_tokens: int
    total_latency_ms: Decimal
    estimated_cost: Optional[Decimal] = None
    currency_code: Optional[str] = None

    @model_validator(mode="after")
    def reconcile(self):
        values = (self.conversation_count, self.passed_count, self.failed_count,
                  self.degraded_count, self.provider_turn_count, self.tool_execution_count,
                  self.successful_tool_execution_count, self.input_tokens, self.output_tokens)
        if any(value < 0 for value in values) or self.total_latency_ms < 0:
            raise ValueError("summary values must be non-negative")
        if self.passed_count + self.failed_count + self.degraded_count > self.conversation_count:
            raise ValueError("summary outcome counts exceed conversations")
        return self
