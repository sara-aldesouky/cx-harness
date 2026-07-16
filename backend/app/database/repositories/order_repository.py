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
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        *,
        customer_id: Optional[UUID] = None,
        status: Optional[str] = None,
        payment_status: Optional[str] = None,
    ) -> list[Order]:
        criteria = self._build_filter_criteria(
            customer_id=customer_id,
            status=status,
            payment_status=payment_status,
        )
        return self._list_filtered(criteria, limit, offset)

    def get_by_id(self, order_id: UUID) -> Optional[Order]:
        return self._session.scalar(select(Order).where(Order.id == order_id))

    def get_by_order_number(self, order_number: str) -> Optional[Order]:
        return self._session.scalar(
            select(Order).where(Order.order_number == order_number)
        )

    def count(
        self,
        *,
        customer_id: Optional[UUID] = None,
        status: Optional[str] = None,
        payment_status: Optional[str] = None,
    ) -> int:
        return self.count_orders(
            customer_id=customer_id,
            status=status,
            payment_status=payment_status,
        )

    def count_orders(
        self,
        *,
        customer_id: Optional[UUID] = None,
        status: Optional[str] = None,
        payment_status: Optional[str] = None,
    ) -> int:
        criteria = self._build_filter_criteria(
            customer_id=customer_id,
            status=status,
            payment_status=payment_status,
        )
        statement = select(func.count()).select_from(Order)
        if criteria:
            statement = statement.where(*criteria)
        return self._session.scalar(statement) or 0

    def list_by_customer_id(
        self,
        customer_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Order]:
        return self.list_orders(
            limit, offset, customer_id=customer_id
        )

    def list_by_status(
        self, status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Order]:
        return self.list_orders(limit, offset, status=status)

    def list_by_payment_status(
        self, payment_status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Order]:
        return self.list_orders(limit, offset, payment_status=payment_status)

    def get_with_customer_and_items(self, order_id: UUID) -> Optional[Order]:
        statement = (
            select(Order)
            .where(Order.id == order_id)
            .options(
                joinedload(Order.customer),
                selectinload(Order.items),
                selectinload(Order.conversations),
            )
        )
        order = self._session.scalar(statement)
        if order is not None:
            order.items.sort(key=lambda item: (item.created_at, item.id))
            order.conversations.sort(
                key=lambda conversation: (
                    conversation.started_at,
                    conversation.id,
                ),
                reverse=True,
            )
        return order

    @staticmethod
    def _build_filter_criteria(
        *,
        customer_id: Optional[UUID],
        status: Optional[str],
        payment_status: Optional[str],
    ) -> list:
        if status is not None:
            validate_filter(status, ORDER_STATUSES, "order status")
        if payment_status is not None:
            validate_filter(payment_status, PAYMENT_STATUSES, "payment status")
        criteria = []
        if customer_id is not None:
            criteria.append(Order.customer_id == customer_id)
        if status is not None:
            criteria.append(Order.status == status)
        if payment_status is not None:
            criteria.append(Order.payment_status == payment_status)
        return criteria

    def _list_filtered(self, criteria: list, limit: int, offset: int) -> list[Order]:
        validate_pagination(limit, offset)
        statement = select(Order)
        if criteria:
            statement = statement.where(*criteria)
        statement = (
            statement.order_by(Order.created_at.desc(), Order.order_number)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
