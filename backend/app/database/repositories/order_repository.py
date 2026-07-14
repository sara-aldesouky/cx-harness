"""Read-only order queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database.models import Order
from app.database.models.order import ORDER_STATUSES, PAYMENT_STATUSES
from app.database.repositories._common import (
    DEFAULT_LIMIT,
    validate_filter,
    validate_pagination,
)


class OrderRepository:
    """Provide read-only access to orders and related records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_orders(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Order]:
        validate_pagination(limit, offset)
        statement = (
            select(Order)
            .order_by(Order.created_at.desc(), Order.order_number)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def get_by_id(self, order_id: UUID) -> Optional[Order]:
        return self._session.scalar(select(Order).where(Order.id == order_id))

    def get_by_order_number(self, order_number: str) -> Optional[Order]:
        return self._session.scalar(
            select(Order).where(Order.order_number == order_number)
        )

    def count(self) -> int:
        return self._session.scalar(select(func.count()).select_from(Order)) or 0

    def list_by_customer_id(
        self,
        customer_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Order]:
        return self._list_filtered(Order.customer_id == customer_id, limit, offset)

    def list_by_status(
        self, status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Order]:
        validate_filter(status, ORDER_STATUSES, "order status")
        return self._list_filtered(Order.status == status, limit, offset)

    def list_by_payment_status(
        self, payment_status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Order]:
        validate_filter(payment_status, PAYMENT_STATUSES, "payment status")
        return self._list_filtered(
            Order.payment_status == payment_status, limit, offset
        )

    def get_with_customer_and_items(self, order_id: UUID) -> Optional[Order]:
        statement = (
            select(Order)
            .where(Order.id == order_id)
            .options(joinedload(Order.customer), selectinload(Order.items))
        )
        order = self._session.scalar(statement)
        if order is not None:
            order.items.sort(key=lambda item: (item.created_at, item.id))
        return order

    def _list_filtered(self, criterion, limit: int, offset: int) -> list[Order]:
        validate_pagination(limit, offset)
        statement = (
            select(Order)
            .where(criterion)
            .order_by(Order.created_at.desc(), Order.order_number)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
