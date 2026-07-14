"""Read-only customer queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database.models import Customer, Order
from app.database.repositories._common import DEFAULT_LIMIT, validate_pagination


class CustomerRepository:
    """Provide read-only access to customers and their orders."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_customers(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Customer]:
        validate_pagination(limit, offset)
        statement = (
            select(Customer)
            .order_by(Customer.last_name, Customer.first_name, Customer.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def get_by_id(self, customer_id: UUID) -> Optional[Customer]:
        return self._session.scalar(
            select(Customer).where(Customer.id == customer_id)
        )

    def get_by_email(self, email: str) -> Optional[Customer]:
        return self._session.scalar(select(Customer).where(Customer.email == email))

    def get_by_phone(self, phone: str) -> Optional[Customer]:
        return self._session.scalar(select(Customer).where(Customer.phone == phone))

    def count(self) -> int:
        return self._session.scalar(select(func.count()).select_from(Customer)) or 0

    def list_orders(
        self,
        customer_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Order]:
        validate_pagination(limit, offset)
        statement = (
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc(), Order.order_number)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def get_with_orders(self, customer_id: UUID) -> Optional[Customer]:
        statement = (
            select(Customer)
            .where(Customer.id == customer_id)
            .options(selectinload(Customer.orders))
        )
        customer = self._session.scalar(statement)
        if customer is not None:
            customer.orders.sort(
                key=lambda order: (order.created_at, order.order_number), reverse=True
            )
        return customer
