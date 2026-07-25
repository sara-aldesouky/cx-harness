"""Normalized refunds, customer-visible events, and eligibility assessments."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


REFUND_STATUSES = ("pending", "processing", "completed", "rejected")
REFUND_EVENT_TYPES = ("requested", "processing", "completed", "rejected")
REFUND_ELIGIBILITY_STATUSES = ("eligible", "not_eligible", "undetermined")


class Refund(Base):
    """One refund against a payment, without processor identifiers."""

    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint(f"status IN {REFUND_STATUSES!r}", name="valid_refund_status"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="non_negative_refund_amount"),
        CheckConstraint("char_length(currency) = 3", name="valid_refund_currency"),
        Index("ix_refunds_payment_created", "payment_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    public_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    payment: Mapped[Payment] = relationship(back_populates="refunds")
    events: Mapped[list[RefundEvent]] = relationship(
        back_populates="refund", cascade="all, delete-orphan", passive_deletes=True
    )


class RefundEvent(Base):
    """One customer-visible refund lifecycle event."""

    __tablename__ = "refund_events"
    __table_args__ = (
        CheckConstraint(f"event_type IN {REFUND_EVENT_TYPES!r}", name="valid_refund_event_type"),
        Index("ix_refund_events_refund_occurred", "refund_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    refund_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("refunds.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    public_description: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    refund: Mapped[Refund] = relationship(back_populates="events")


class RefundEligibility(Base):
    """Latest trusted business eligibility assessment for one order."""

    __tablename__ = "refund_eligibilities"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_refund_eligibilities_order_id"),
        CheckConstraint(
            f"status IN {REFUND_ELIGIBILITY_STATUSES!r}", name="valid_refund_eligibility_status"
        ),
        Index("ix_refund_eligibilities_order_id", "order_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    public_reason: Mapped[str] = mapped_column(Text, nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    order: Mapped[Order] = relationship(back_populates="refund_eligibility")
