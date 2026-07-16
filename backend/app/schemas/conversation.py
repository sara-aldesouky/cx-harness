"""Conversation response schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from app.schemas.common import CustomerReference, OrderReference, ORMResponse
from app.schemas.message import MessageSummary
from app.schemas.model_run import ModelRunSummary


class ConversationSummary(ORMResponse):
    id: UUID
    customer_id: UUID
    related_order_id: Optional[UUID]
    status: str
    channel: str
    active_model: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    customer: CustomerReference
    related_order: Optional[OrderReference]
    messages: list[MessageSummary]
    model_runs: list[ModelRunSummary]
