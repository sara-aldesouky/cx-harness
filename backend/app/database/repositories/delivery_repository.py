"""Read-only delivery and delivery-event queries."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import Delivery, DeliveryEvent, Order
from app.database.repositories._common import DEFAULT_LIMIT, validate_pagination


class DeliveryRepository:
    """Provide deterministic read-only access to normalized delivery data."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_order_number(self, order_number: str) -> Optional[Delivery]:
        return self._session.scalar(
            select(Delivery)
            .join(Delivery.order)
            .where(Order.order_number == order_number)
            .options(joinedload(Delivery.order))
        )

    def get_owned_by_order_number(
        self, order_number: str, customer_id: UUID
    ) -> Optional[Delivery]:
        return self._session.scalar(
            select(Delivery)
            .join(Delivery.order)
            .where(
                Order.order_number == order_number,
                Order.customer_id == customer_id,
            )
            .options(joinedload(Delivery.order))
        )

    def get_latest_event(self, delivery_id: UUID) -> Optional[DeliveryEvent]:
        return self._session.scalar(
            select(DeliveryEvent)
            .where(DeliveryEvent.delivery_id == delivery_id)
            .order_by(DeliveryEvent.occurred_at.desc(), DeliveryEvent.id.desc())
            .limit(1)
        )

    def list_events(
        self,
        delivery_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[DeliveryEvent]:
        validate_pagination(limit, offset)
        return list(
            self._session.scalars(
                select(DeliveryEvent)
                .where(DeliveryEvent.delivery_id == delivery_id)
                .order_by(DeliveryEvent.occurred_at.desc(), DeliveryEvent.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )

    def count_events(self, delivery_id: UUID) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(DeliveryEvent)
                .where(DeliveryEvent.delivery_id == delivery_id)
            )
            or 0
        )
