"""Normalized delivery state and customer-visible event history."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


DELIVERY_STATUSES = (
    "not_started",
    "scheduled",
    "out_for_delivery",
    "delayed",
    "delivered",
    "failed",
)
DELIVERY_EVENT_TYPES = (
    "scheduled",
    "picked_up",
    "out_for_delivery",
    "delayed",
    "delivery_attempted",
    "delivered",
    "failed",
)


class Delivery(Base):
    """Current normalized delivery state for exactly one order."""

    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_deliveries_order_id"),
        CheckConstraint(
            f"status IN {DELIVERY_STATUSES!r}", name="valid_delivery_status"
        ),
        CheckConstraint(
            "(window_start IS NULL AND window_end IS NULL) OR "
            "(window_start IS NOT NULL AND window_end IS NOT NULL "
            "AND window_end > window_start)",
            name="valid_delivery_window",
        ),
        Index("ix_deliveries_order_id", "order_id"),
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
    estimated_delivery_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    window_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    window_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    order: Mapped[Order] = relationship(back_populates="delivery")
    events: Mapped[list[DeliveryEvent]] = relationship(
        back_populates="delivery",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DeliveryEvent(Base):
    """One customer-visible event in a delivery's ordered history."""

    __tablename__ = "delivery_events"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN {DELIVERY_EVENT_TYPES!r}",
            name="valid_delivery_event_type",
        ),
        Index(
            "ix_delivery_events_delivery_occurred",
            "delivery_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    delivery_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("deliveries.id", ondelete="CASCADE"),
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

    delivery: Mapped[Delivery] = relationship(back_populates="events")
