"""Customer-support conversation database model."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


CONVERSATION_STATUSES = (
    "open",
    "waiting_for_customer",
    "waiting_for_agent",
    "resolved",
    "escalated",
    "closed",
)
CONVERSATION_CHANNELS = ("web", "mobile", "whatsapp", "internal_test")


class Conversation(Base):
    """A customer-support interaction, optionally related to an order."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            f"status IN {CONVERSATION_STATUSES!r}", name="valid_status"
        ),
        CheckConstraint(
            f"channel IN {CONVERSATION_CHANNELS!r}", name="valid_channel"
        ),
        Index("ix_conversations_customer_id", "customer_id"),
        Index("ix_conversations_related_order_id", "related_order_id"),
        Index("ix_conversations_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    customer_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    related_order_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    active_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
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

    customer: Mapped[Customer] = relationship(back_populates="conversations")
    related_order: Mapped[Optional[Order]] = relationship(
        back_populates="conversations"
    )
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.sequence_number",
    )
    model_runs: Mapped[list[ModelRun]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
