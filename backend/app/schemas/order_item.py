"""Order-item response schemas."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.schemas.common import ORMResponse


class OrderItemSummary(ORMResponse):
    id: UUID
    order_id: UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    item_status: str
    created_at: datetime


class OrderItemDetail(OrderItemSummary):
    pass
