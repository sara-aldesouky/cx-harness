"""Model-run response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.schemas.common import ORMResponse
from app.schemas.evaluation import EvaluationSummary
from app.schemas.tool_call import ToolCallSummary


class ModelRunSummary(ORMResponse):
    id: UUID
    conversation_id: UUID
    provider: str
    model_name: str
    status: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    latency_ms: Optional[int]
    estimated_cost: Optional[Decimal]
    temperature: Optional[Decimal]
    success: bool
    error_message: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]
    created_at: datetime


class ModelRunDetail(ModelRunSummary):
    tool_calls: list[ToolCallSummary]
    evaluations: list[EvaluationSummary]
