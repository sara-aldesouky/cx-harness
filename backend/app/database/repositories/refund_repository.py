"""Read-only, customer-scoped refund queries."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import Order, Payment, Refund, RefundEligibility, RefundEvent
from app.database.repositories._common import DEFAULT_LIMIT, validate_pagination


class RefundRepository:
    """Read refund facts without exposing internal or processor identifiers."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_latest_owned_by_order_number(
        self, order_number: str, customer_id: UUID
    ) -> Optional[Refund]:
        return self._session.scalar(
            select(Refund)
            .join(Refund.payment)
            .join(Payment.order)
            .where(Order.order_number == order_number, Order.customer_id == customer_id)
            .options(joinedload(Refund.payment).joinedload(Payment.order))
            .order_by(Refund.requested_at.desc(), Refund.id.desc())
            .limit(1)
        )

    def list_owned_by_order_number(
        self, order_number: str, customer_id: UUID, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Refund]:
        validate_pagination(limit, offset)
        return list(self._session.scalars(
            select(Refund)
            .join(Refund.payment)
            .join(Payment.order)
            .where(Order.order_number == order_number, Order.customer_id == customer_id)
            .options(joinedload(Refund.payment).joinedload(Payment.order))
            .order_by(Refund.requested_at.desc(), Refund.id.desc())
            .offset(offset).limit(limit)
        ).all())

    def count_owned_by_order_number(self, order_number: str, customer_id: UUID) -> int:
        return self._session.scalar(
            select(func.count()).select_from(Refund).join(Refund.payment).join(Payment.order)
            .where(Order.order_number == order_number, Order.customer_id == customer_id)
        ) or 0

    def get_latest_event_for_order(
        self, order_number: str, customer_id: UUID
    ) -> Optional[RefundEvent]:
        return self._session.scalar(
            select(RefundEvent).join(RefundEvent.refund).join(Refund.payment).join(Payment.order)
            .where(Order.order_number == order_number, Order.customer_id == customer_id)
            .order_by(RefundEvent.occurred_at.desc(), RefundEvent.id.desc()).limit(1)
        )

    def list_events_for_order(
        self,
        order_number: str,
        customer_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[RefundEvent]:
        validate_pagination(limit, offset)
        return list(
            self._session.scalars(
                select(RefundEvent)
                .join(RefundEvent.refund)
                .join(Refund.payment)
                .join(Payment.order)
                .where(
                    Order.order_number == order_number,
                    Order.customer_id == customer_id,
                )
                .order_by(
                    RefundEvent.occurred_at.desc(), RefundEvent.id.desc()
                )
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def count_events_for_order(self, order_number: str, customer_id: UUID) -> int:
        return self._session.scalar(
            select(func.count())
            .select_from(RefundEvent)
            .join(RefundEvent.refund)
            .join(Refund.payment)
            .join(Payment.order)
            .where(
                Order.order_number == order_number,
                Order.customer_id == customer_id,
            )
        ) or 0

    def get_eligibility_for_order(
        self, order_number: str, customer_id: UUID
    ) -> Optional[RefundEligibility]:
        return self._session.scalar(
            select(RefundEligibility).join(RefundEligibility.order)
            .where(Order.order_number == order_number, Order.customer_id == customer_id)
            .options(joinedload(RefundEligibility.order))
        )
