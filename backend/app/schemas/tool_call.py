"""Tool-call response schemas."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from app.schemas.common import ORMResponse


class ToolCallSummary(ORMResponse):
    id: UUID
    model_run_id: UUID
    tool_name: str
    status: str
    success: bool
    latency_ms: Optional[int]
    requested_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime


class ToolCallDetail(ToolCallSummary):
    input_json: dict[str, Any]
    output_json: Optional[dict[str, Any]]
    error_message: Optional[str]
