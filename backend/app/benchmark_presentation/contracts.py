"""Strict HTTP-facing contracts for benchmark report discovery."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PresentationContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BenchmarkRunListItem(PresentationContract):
    run_id: UUID
    run_key: str
    suite_key: str
    suite_version: str
    suite_content_hash: str
    model_name: str
    provider_name: str
    scoring_policy_key: str
    scoring_policy_version: str
    status: str
    expected_test_count: int
    stored_test_count: int
    completed_test_count: int
    pass_rate: Optional[Decimal]
    overall_score: Optional[Decimal]
    score_coverage: Optional[Decimal]
    created_at: datetime
    report_eligible: bool


class BenchmarkRunPage(PresentationContract):
    items: tuple[BenchmarkRunListItem, ...]
    total: int
    limit: int
    offset: int


class BenchmarkCaseEvidence(PresentationContract):
    """Read-only presentation evidence; never participates in scoring."""

    test_case_id: str
    language: str
    category: str
    customer_question: str
    model: str
    model_response: str
    expected_answer: Optional[str] = None
    passed: bool
    hallucination: bool
    grounded: bool
    correct_tool: Optional[bool]
    tool_used: tuple[str, ...] = ()
    intent_match: Optional[bool]
    latency_ms: Decimal
    tokens: int
    cost: Optional[Decimal]
    currency_code: Optional[str]
    failure_category: Optional[str]
    failure_explanation: Optional[str]
    evaluation_scores: dict[str, Any] = Field(default_factory=dict)
    tool_calls: tuple[dict[str, Any], ...] = ()
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ComparisonRequest(PresentationContract):
    run_ids: tuple[UUID, ...]
    scoring_policy_key: Optional[str] = None
    scoring_policy_version: Optional[str] = None

    @model_validator(mode="after")
    def validate_runs(self) -> "ComparisonRequest":
        if len(self.run_ids) < 2:
            raise ValueError("at least two runs are required")
        if len(self.run_ids) > 8:
            raise ValueError("at most eight runs may be compared")
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("duplicate run identifiers are not allowed")
        return self


class PresentationError(PresentationContract):
    code: str
    message: str
    details: tuple[str, ...] = ()
