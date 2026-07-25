"""Normalized payment attempts and customer-visible payment events."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


PAYMENT_RECORD_STATUSES = (
    "pending",
    "succeeded",
    "failed",
    "refunded",
    "partially_refunded",
)
PAYMENT_METHOD_TYPES = ("card", "cash", "wallet", "bank_transfer")
PAYMENT_EVENT_TYPES = (
    "initiated",
    "authorized",
    "captured",
    "failed",
    "refund_pending",
    "refunded",
    "partially_refunded",
)


class Payment(Base):
    """One payment attempt for an order, without processor secrets."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            f"status IN {PAYMENT_RECORD_STATUSES!r}", name="valid_payment_record_status"
        ),
        CheckConstraint(
            f"method_type IN {PAYMENT_METHOD_TYPES!r}", name="valid_payment_method_type"
        ),
        CheckConstraint("amount >= 0", name="non_negative_payment_amount"),
        CheckConstraint("char_length(currency) = 3", name="valid_payment_currency"),
        Index("ix_payments_order_created", "order_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    method_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    failure_reason_public: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    order: Mapped[Order] = relationship(back_populates="payments")
    events: Mapped[list[PaymentEvent]] = relationship(
        back_populates="payment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    refunds: Mapped[list[Refund]] = relationship(
        back_populates="payment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PaymentEvent(Base):
    """One customer-visible lifecycle event for a payment attempt."""

    __tablename__ = "payment_events"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN {PAYMENT_EVENT_TYPES!r}",
            name="valid_payment_event_type",
        ),
        Index(
            "ix_payment_events_payment_occurred",
            "payment_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    payment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    public_description: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    payment: Mapped[Payment] = relationship(back_populates="events")
