"""Narrow resolver-facing order repository boundary and established-repository adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.database.repositories import OrderRepository


class OrderResolutionRecord(BaseModel):
    """Minimal order data needed for deterministic resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    created_at: datetime

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("order_number must not be empty")
        return normalized

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a UTC timezone")
        return value.astimezone(timezone.utc)


@runtime_checkable
class OrderResolutionRepository(Protocol):
    """Customer-scoped read boundary; implementations must not leak ownership."""

    def find_for_customer(
        self, customer_id: UUID, order_number: str
    ) -> Optional[OrderResolutionRecord]: ...

    def list_active_for_customer(
        self, customer_id: UUID
    ) -> tuple[OrderResolutionRecord, ...]: ...

    def latest_for_customer(
        self, customer_id: UUID
    ) -> Optional[OrderResolutionRecord]: ...


class ExistingOrderRepositoryAdapter:
    """Adapt the established repository without exposing ORM records upstream."""

    def __init__(self, repository: OrderRepository) -> None:
        if not isinstance(repository, OrderRepository):
            raise TypeError("repository must be an OrderRepository")
        self._repository = repository

    @staticmethod
    def _record(order) -> OrderResolutionRecord:
        return OrderResolutionRecord(
            order_number=order.order_number,
            created_at=order.created_at,
        )

    @staticmethod
    def _ordered(records: list[OrderResolutionRecord]) -> tuple[OrderResolutionRecord, ...]:
        return tuple(
            sorted(
                records,
                key=lambda item: (item.created_at, item.order_number),
                reverse=True,
            )
        )

    def find_for_customer(
        self, customer_id: UUID, order_number: str
    ) -> Optional[OrderResolutionRecord]:
        order = self._repository.get_by_order_number(order_number)
        if order is None or order.customer_id != customer_id:
            return None
        return self._record(order)

    def list_active_for_customer(
        self, customer_id: UUID
    ) -> tuple[OrderResolutionRecord, ...]:
        count = self._repository.count_current_by_customer_id(customer_id)
        if count == 0:
            return ()
        orders = self._repository.list_current_by_customer_id(
            customer_id, limit=count, offset=0
        )
        return self._ordered([self._record(order) for order in orders])

    def latest_for_customer(
        self, customer_id: UUID
    ) -> Optional[OrderResolutionRecord]:
        count = self._repository.count_orders(customer_id=customer_id)
        if count == 0:
            return None
        orders = self._repository.list_by_customer_id(
            customer_id, limit=count, offset=0
        )
        ordered = self._ordered([self._record(order) for order in orders])
        return ordered[0]
