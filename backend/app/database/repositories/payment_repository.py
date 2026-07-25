"""Read-only payment and payment-event queries."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import Order, Payment, PaymentEvent
from app.database.repositories._common import DEFAULT_LIMIT, validate_pagination


class PaymentRepository:
    """Read normalized payment attempts through customer ownership boundaries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_latest_owned_by_order_number(
        self, order_number: str, customer_id: UUID
    ) -> Optional[Payment]:
        return self._session.scalar(
            select(Payment)
            .join(Payment.order)
            .where(
                Order.order_number == order_number,
                Order.customer_id == customer_id,
            )
            .options(joinedload(Payment.order))
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(1)
        )

    def get_latest_event(self, payment_id: UUID) -> Optional[PaymentEvent]:
        return self._session.scalar(
            select(PaymentEvent)
            .where(PaymentEvent.payment_id == payment_id)
            .order_by(PaymentEvent.occurred_at.desc(), PaymentEvent.id.desc())
            .limit(1)
        )

    def get_latest_event_for_order(
        self, order_number: str, customer_id: UUID
    ) -> Optional[PaymentEvent]:
        return self._session.scalar(
            select(PaymentEvent)
            .join(PaymentEvent.payment)
            .join(Payment.order)
            .where(
                Order.order_number == order_number,
                Order.customer_id == customer_id,
            )
            .order_by(PaymentEvent.occurred_at.desc(), PaymentEvent.id.desc())
            .limit(1)
        )

    def list_events(
        self,
        payment_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[PaymentEvent]:
        validate_pagination(limit, offset)
        return list(
            self._session.scalars(
                select(PaymentEvent)
                .where(PaymentEvent.payment_id == payment_id)
                .order_by(PaymentEvent.occurred_at.desc(), PaymentEvent.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def count_events(self, payment_id: UUID) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(PaymentEvent)
                .where(PaymentEvent.payment_id == payment_id)
            )
            or 0
        )

    def list_events_for_order(
        self,
        order_number: str,
        customer_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[PaymentEvent]:
        validate_pagination(limit, offset)
        return list(
            self._session.scalars(
                select(PaymentEvent)
                .join(PaymentEvent.payment)
                .join(Payment.order)
                .where(
                    Order.order_number == order_number,
                    Order.customer_id == customer_id,
                )
                .order_by(PaymentEvent.occurred_at.desc(), PaymentEvent.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def count_events_for_order(
        self, order_number: str, customer_id: UUID
    ) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(PaymentEvent)
                .join(PaymentEvent.payment)
                .join(Payment.order)
                .where(
                    Order.order_number == order_number,
                    Order.customer_id == customer_id,
                )
            )
            or 0
        )
