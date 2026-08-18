"""Order-cancellation business operation and persistence ports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Order
from app.database.repositories import OrderRepository
from app.write_operations.contracts import (
    BaseWriteOperation,
    WriteExecutionContext,
    WriteValidationDecision,
)


CANCELLABLE_ORDER_STATUSES = frozenset({"pending", "confirmed", "preparing"})


class CancelOrderInput(BaseModel):
    """Customer-facing order reference; trusted identity stays in context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or len(normalized) > 64:
            raise ValueError("order_number must contain 1 to 64 characters")
        return normalized


class CancelOrderOutput(BaseModel):
    """Customer-safe cancellation outcome without internal identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    status: str
    cancelled_at: datetime


class OrderCancellationSnapshot(BaseModel):
    """Minimal immutable state required for cancellation decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    customer_id: UUID
    status: str


class OrderCancellationReader(Protocol):
    def get(self, order_number: str) -> Optional[OrderCancellationSnapshot]: ...


class OrderCancellationStore(Protocol):
    def get_for_update(
        self, order_number: str
    ) -> Optional[OrderCancellationSnapshot]: ...

    def mark_cancelled(self, order_number: str, cancelled_at: datetime) -> None: ...


class OrderCancellationPolicy:
    """Single declarative source for extensible cancellation eligibility."""

    @staticmethod
    def evaluate(
        snapshot: Optional[OrderCancellationSnapshot], customer_id: UUID
    ) -> WriteValidationDecision:
        # Absence and ownership mismatch are intentionally indistinguishable.
        if snapshot is None or snapshot.customer_id != customer_id:
            return WriteValidationDecision.deny(
                "order_not_found", "The requested order was not found."
            )
        if snapshot.status == "cancelled":
            return WriteValidationDecision.deny(
                "order_already_cancelled", "This order has already been cancelled."
            )
        if snapshot.status not in CANCELLABLE_ORDER_STATUSES:
            return WriteValidationDecision.deny(
                "order_cancellation_not_allowed",
                "This order can no longer be cancelled.",
            )
        return WriteValidationDecision.allow()


class CancelOrderOperation(
    BaseWriteOperation[CancelOrderInput, CancelOrderOutput, Session]
):
    """Apply cancellation business rules without owning a transaction."""

    name = "cancel_order"
    version = "1.0.0"
    input_schema = CancelOrderInput
    output_schema = CancelOrderOutput

    def __init__(
        self,
        reader: OrderCancellationReader,
        store_factory: Callable[[Session], OrderCancellationStore],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not callable(getattr(reader, "get", None)):
            raise TypeError("reader must provide get()")
        if not callable(store_factory):
            raise TypeError("store_factory must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._reader = reader
        self._store_factory = store_factory
        self._clock = clock

    def audit_reference(
        self, input_model: CancelOrderInput, outcome: Optional[CancelOrderOutput] = None
    ) -> str:
        return input_model.order_number

    def validate(
        self, context: WriteExecutionContext, input_model: CancelOrderInput
    ) -> WriteValidationDecision:
        customer_id = context.execution_context.customer_id
        assert customer_id is not None  # guaranteed by WriteExecutionContext
        return OrderCancellationPolicy.evaluate(
            self._reader.get(input_model.order_number), customer_id
        )

    def apply(
        self,
        context: WriteExecutionContext,
        input_model: CancelOrderInput,
        transaction: Session,
    ) -> CancelOrderOutput:
        store = self._store_factory(transaction)
        snapshot = store.get_for_update(input_model.order_number)
        customer_id = context.execution_context.customer_id
        assert customer_id is not None
        decision = OrderCancellationPolicy.evaluate(snapshot, customer_id)
        if not decision.allowed:
            # A concurrent state change must roll back rather than overwrite it.
            raise OrderCancellationStateChanged(decision.failure_code or "state_changed")
        cancelled_at = self._clock()
        if cancelled_at.tzinfo is None or cancelled_at.utcoffset() is None:
            raise ValueError("cancellation clock must return a timezone-aware value")
        store.mark_cancelled(input_model.order_number, cancelled_at)
        return CancelOrderOutput(
            order_number=input_model.order_number,
            status="cancelled",
            cancelled_at=cancelled_at,
        )


class OrderCancellationStateChanged(RuntimeError):
    """Internal signal that locked state no longer matches validation."""


class SQLAlchemyOrderCancellationReader:
    """Read minimal order state using the established OrderRepository."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory

    def get(self, order_number: str) -> Optional[OrderCancellationSnapshot]:
        with self._session_factory() as session:
            order = OrderRepository(session).get_by_order_number(order_number)
            return _snapshot(order)


class SQLAlchemyOrderCancellationStore:
    """Persistence adapter used only inside the framework-owned transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._locked_order: Optional[Order] = None

    def get_for_update(
        self, order_number: str
    ) -> Optional[OrderCancellationSnapshot]:
        self._locked_order = self._session.scalar(
            select(Order)
            .where(Order.order_number == order_number)
            .with_for_update()
        )
        return _snapshot(self._locked_order)

    def mark_cancelled(self, order_number: str, cancelled_at: datetime) -> None:
        if self._locked_order is None or self._locked_order.order_number != order_number:
            raise RuntimeError("order must be locked before cancellation")
        self._locked_order.status = "cancelled"
        self._locked_order.updated_at = cancelled_at


def _snapshot(order: Optional[Order]) -> Optional[OrderCancellationSnapshot]:
    if order is None:
        return None
    return OrderCancellationSnapshot(
        order_number=order.order_number,
        customer_id=order.customer_id,
        status=order.status,
    )
