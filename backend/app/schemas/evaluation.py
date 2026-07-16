"""Evaluation response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from app.schemas.common import ORMResponse


class EvaluationSummary(ORMResponse):
    id: UUID
    model_run_id: UUID
    evaluator_type: str
    evaluator_name: str
    overall_score: Optional[Decimal]
    passed: bool
    evaluated_at: datetime
    created_at: datetime


class EvaluationDetail(EvaluationSummary):
    intent_score: Optional[Decimal]
    tool_score: Optional[Decimal]
    tone_score: Optional[Decimal]
    arabic_score: Optional[Decimal]
    franco_score: Optional[Decimal]
    policy_score: Optional[Decimal]
    resolution_score: Optional[Decimal]
    notes: Optional[str]
    details_json: Optional[dict[str, Any]]
