"""Customer response schemas."""

from datetime import datetime
from uuid import UUID

from app.schemas.common import ConversationReference, ORMResponse
from app.schemas.order import OrderSummary


class CustomerSummary(ORMResponse):
    id: UUID
    first_name: str
    last_name: str
    phone: str
    email: str
    preferred_language: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerDetail(CustomerSummary):
    orders: list[OrderSummary]
    conversations: list[ConversationReference]
