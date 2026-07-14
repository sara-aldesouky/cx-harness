"""Read-only order-item queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import OrderItem
from app.database.models.order_item import ITEM_STATUSES
from app.database.repositories._common import (
    DEFAULT_LIMIT,
    validate_filter,
    validate_pagination,
)


class OrderItemRepository:
    """Provide read-only access to order items."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_items(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[OrderItem]:
        validate_pagination(limit, offset)
        statement = (
            select(OrderItem)
            .order_by(OrderItem.created_at, OrderItem.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def get_by_id(self, item_id: UUID) -> Optional[OrderItem]:
        return self._session.scalar(select(OrderItem).where(OrderItem.id == item_id))

    def list_by_order_id(
        self,
        order_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[OrderItem]:
        return self._list_filtered(OrderItem.order_id == order_id, limit, offset)

    def list_by_status(
        self, item_status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[OrderItem]:
        validate_filter(item_status, ITEM_STATUSES, "item status")
        return self._list_filtered(
            OrderItem.item_status == item_status, limit, offset
        )

    def count(self) -> int:
        return self._session.scalar(select(func.count()).select_from(OrderItem)) or 0

    def _list_filtered(self, criterion, limit: int, offset: int) -> list[OrderItem]:
        validate_pagination(limit, offset)
        statement = (
            select(OrderItem)
            .where(criterion)
            .order_by(OrderItem.created_at, OrderItem.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
