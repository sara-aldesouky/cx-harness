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
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        *,
        order_id: Optional[UUID] = None,
        item_status: Optional[str] = None,
    ) -> list[OrderItem]:
        criteria = self._build_filter_criteria(
            order_id=order_id, item_status=item_status
        )
        return self._list_filtered(criteria, limit, offset)

    def get_by_id(self, item_id: UUID) -> Optional[OrderItem]:
        return self._session.scalar(select(OrderItem).where(OrderItem.id == item_id))

    def list_by_order_id(
        self,
        order_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[OrderItem]:
        return self.list_items(limit, offset, order_id=order_id)

    def list_by_status(
        self, item_status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[OrderItem]:
        return self.list_items(limit, offset, item_status=item_status)

    def count(
        self,
        *,
        order_id: Optional[UUID] = None,
        item_status: Optional[str] = None,
    ) -> int:
        return self.count_items(order_id=order_id, item_status=item_status)

    def count_items(
        self,
        *,
        order_id: Optional[UUID] = None,
        item_status: Optional[str] = None,
    ) -> int:
        criteria = self._build_filter_criteria(
            order_id=order_id, item_status=item_status
        )
        statement = select(func.count()).select_from(OrderItem)
        if criteria:
            statement = statement.where(*criteria)
        return self._session.scalar(statement) or 0

    @staticmethod
    def _build_filter_criteria(
        *, order_id: Optional[UUID], item_status: Optional[str]
    ) -> list:
        if item_status is not None:
            validate_filter(item_status, ITEM_STATUSES, "item status")
        criteria = []
        if order_id is not None:
            criteria.append(OrderItem.order_id == order_id)
        if item_status is not None:
            criteria.append(OrderItem.item_status == item_status)
        return criteria

    def _list_filtered(
        self, criteria: list, limit: int, offset: int
    ) -> list[OrderItem]:
        validate_pagination(limit, offset)
        statement = select(OrderItem)
        if criteria:
            statement = statement.where(*criteria)
        statement = (
            statement.order_by(OrderItem.created_at, OrderItem.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
