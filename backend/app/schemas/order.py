"""Order response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from app.schemas.common import CustomerReference, ConversationReference, ORMResponse
from app.schemas.order_item import OrderItemSummary


class OrderSummary(ORMResponse):
    id: UUID
    order_number: str
    customer_id: UUID
    status: str
    payment_status: str
    total_amount: Decimal
    delivery_address: str
    estimated_delivery_time: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class OrderDetail(OrderSummary):
    customer: CustomerReference
    items: list[OrderItemSummary]
    conversations: list[ConversationReference]
