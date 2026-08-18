"""Refund-initiation business policy and persistence adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Order, Payment, Refund, RefundEligibility, RefundEvent
from app.database.repositories import OrderRepository
from app.write_operations.contracts import (
    BaseWriteOperation,
    WriteExecutionContext,
    WriteValidationDecision,
)


class InitiateRefundInput(BaseModel):
    """Customer-facing order reference; no payment or customer identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or len(normalized) > 64:
            raise ValueError("order_number must contain 1 to 64 characters")
        return normalized


class InitiateRefundOutput(BaseModel):
    """Customer-safe request acknowledgement without financial identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    refund_status: str
    request_created: bool
    requested_at: datetime


class RefundInitiationSnapshot(BaseModel):
    """Minimal immutable facts required to evaluate refund initiation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    customer_id: UUID
    order_status: str
    order_payment_status: str
    payment_id: Optional[UUID] = None
    payment_status: Optional[str] = None
    payment_currency: Optional[str] = None
    eligibility_status: Optional[str] = None
    existing_refund_status: Optional[str] = None
    existing_refund_requested_at: Optional[datetime] = None


class RefundInitiationReader(Protocol):
    def get(self, order_number: str) -> Optional[RefundInitiationSnapshot]: ...


class RefundInitiationStore(Protocol):
    def get_for_update(
        self, order_number: str
    ) -> Optional[RefundInitiationSnapshot]: ...

    def create_request(
        self, payment_id: UUID, currency: str, requested_at: datetime
    ) -> None: ...


class RefundPolicy:
    """Central declarative eligibility and duplicate-prevention policy."""

    @staticmethod
    def evaluate(
        snapshot: Optional[RefundInitiationSnapshot], customer_id: UUID
    ) -> WriteValidationDecision:
        if snapshot is None or snapshot.customer_id != customer_id:
            return WriteValidationDecision.deny(
                "order_not_found", "The requested order was not found."
            )
        if snapshot.existing_refund_status is not None:
            return WriteValidationDecision.deny(
                "refund_already_requested",
                "A refund has already been requested for this order.",
            )
        if snapshot.order_status != "delivered":
            return WriteValidationDecision.deny(
                "refund_not_allowed", "This order is not eligible for a refund request."
            )
        if (
            snapshot.order_payment_status != "paid"
            or snapshot.payment_id is None
            or snapshot.payment_status != "succeeded"
            or snapshot.payment_currency is None
        ):
            return WriteValidationDecision.deny(
                "refund_not_allowed", "This order is not eligible for a refund request."
            )
        if snapshot.eligibility_status != "eligible":
            return WriteValidationDecision.deny(
                "refund_not_allowed", "This order is not eligible for a refund request."
            )
        return WriteValidationDecision.allow()


class InitiateRefundOperation(
    BaseWriteOperation[InitiateRefundInput, InitiateRefundOutput, Session]
):
    """Create a refund request without settlement or transaction ownership."""

    name = "initiate_refund"
    version = "1.0.0"
    input_schema = InitiateRefundInput
    output_schema = InitiateRefundOutput

    def __init__(
        self,
        reader: RefundInitiationReader,
        store_factory: Callable[[Session], RefundInitiationStore],
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
        self,
        input_model: InitiateRefundInput,
        outcome: Optional[InitiateRefundOutput] = None,
    ) -> str:
        return input_model.order_number

    def success_message(self, outcome: InitiateRefundOutput) -> str:
        return (
            "A refund has already been requested for this order."
            if not outcome.request_created
            else "Your refund request was submitted successfully."
        )

    def business_change_applied(self, outcome: InitiateRefundOutput) -> bool:
        return outcome.request_created

    def validate(
        self, context: WriteExecutionContext, input_model: InitiateRefundInput
    ) -> WriteValidationDecision:
        customer_id = context.execution_context.customer_id
        assert customer_id is not None
        return RefundPolicy.evaluate(
            self._reader.get(input_model.order_number), customer_id
        )

    def apply(
        self,
        context: WriteExecutionContext,
        input_model: InitiateRefundInput,
        transaction: Session,
    ) -> InitiateRefundOutput:
        store = self._store_factory(transaction)
        snapshot = store.get_for_update(input_model.order_number)
        customer_id = context.execution_context.customer_id
        assert customer_id is not None
        decision = RefundPolicy.evaluate(snapshot, customer_id)
        if not decision.allowed:
            if (
                decision.failure_code == "refund_already_requested"
                and snapshot is not None
                and snapshot.existing_refund_requested_at is not None
            ):
                return InitiateRefundOutput(
                    order_number=input_model.order_number,
                    refund_status=snapshot.existing_refund_status or "pending",
                    request_created=False,
                    requested_at=snapshot.existing_refund_requested_at,
                )
            raise RefundInitiationStateChanged(
                decision.failure_code or "refund_state_changed"
            )

        requested_at = self._clock()
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError("refund clock must return a timezone-aware value")
        assert snapshot is not None
        assert snapshot.payment_id is not None
        assert snapshot.payment_currency is not None
        store.create_request(
            snapshot.payment_id, snapshot.payment_currency, requested_at
        )
        return InitiateRefundOutput(
            order_number=input_model.order_number,
            refund_status="pending",
            request_created=True,
            requested_at=requested_at,
        )


class RefundInitiationStateChanged(RuntimeError):
    """Internal signal that locked eligibility changed after preflight."""


class SQLAlchemyRefundInitiationReader:
    """Read existing normalized refund facts outside the transaction."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory

    def get(self, order_number: str) -> Optional[RefundInitiationSnapshot]:
        with self._session_factory() as session:
            order = OrderRepository(session).get_by_order_number(order_number)
            return _snapshot(session, order)


class SQLAlchemyRefundInitiationStore:
    """Lock the order and create normalized refund records atomically."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._locked_order: Optional[Order] = None

    def get_for_update(
        self, order_number: str
    ) -> Optional[RefundInitiationSnapshot]:
        self._locked_order = self._session.scalar(
            select(Order).where(Order.order_number == order_number).with_for_update()
        )
        return _snapshot(self._session, self._locked_order)

    def create_request(
        self, payment_id: UUID, currency: str, requested_at: datetime
    ) -> None:
        if self._locked_order is None:
            raise RuntimeError("order must be locked before refund initiation")
        refund = Refund(
            payment_id=payment_id,
            status="pending",
            amount=None,
            currency=currency,
            public_reason="Refund requested.",
            requested_at=requested_at,
            processed_at=None,
        )
        refund.events.append(
            RefundEvent(
                event_type="requested",
                public_description="Your refund request was received.",
                occurred_at=requested_at,
            )
        )
        self._session.add(refund)


def _snapshot(
    session: Session, order: Optional[Order]
) -> Optional[RefundInitiationSnapshot]:
    if order is None:
        return None
    payment = session.scalar(
        select(Payment)
        .where(Payment.order_id == order.id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(1)
    )
    eligibility = session.scalar(
        select(RefundEligibility).where(RefundEligibility.order_id == order.id)
    )
    existing_refund = session.scalar(
        select(Refund)
        .join(Refund.payment)
        .where(Payment.order_id == order.id)
        .order_by(Refund.requested_at.desc(), Refund.id.desc())
        .limit(1)
    )
    return RefundInitiationSnapshot(
        order_number=order.order_number,
        customer_id=order.customer_id,
        order_status=order.status,
        order_payment_status=order.payment_status,
        payment_id=payment.id if payment is not None else None,
        payment_status=payment.status if payment is not None else None,
        payment_currency=payment.currency if payment is not None else None,
        eligibility_status=eligibility.status if eligibility is not None else None,
        existing_refund_status=(
            existing_refund.status if existing_refund is not None else None
        ),
        existing_refund_requested_at=(
            existing_refund.requested_at if existing_refund is not None else None
        ),
    )
