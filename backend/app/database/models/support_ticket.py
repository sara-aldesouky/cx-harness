"""Minimal normalized customer support ticket persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


SUPPORT_TICKET_CATEGORIES = (
    "general_inquiry",
    "order_issue",
    "delivery_issue",
    "payment_issue",
    "refund_issue",
    "technical_issue",
)
SUPPORT_TICKET_PRIORITIES = ("low", "medium", "high", "critical")
SUPPORT_TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")


class SupportTicket(Base):
    """One customer issue awaiting future support workflow handling."""

    __tablename__ = "support_tickets"
    __table_args__ = (
        CheckConstraint(
            f"category IN {SUPPORT_TICKET_CATEGORIES!r}",
            name="valid_support_ticket_category",
        ),
        CheckConstraint(
            f"priority IN {SUPPORT_TICKET_PRIORITIES!r}",
            name="valid_support_ticket_priority",
        ),
        CheckConstraint(
            f"status IN {SUPPORT_TICKET_STATUSES!r}",
            name="valid_support_ticket_status",
        ),
        Index("ix_support_tickets_customer_id", "customer_id"),
        Index("ix_support_tickets_related_order_id", "related_order_id"),
        Index("ix_support_tickets_ticket_reference", "ticket_reference", unique=True),
        Index(
            "uq_support_tickets_active_issue",
            "customer_id",
            "issue_fingerprint",
            unique=True,
            postgresql_where=text("status IN ('open', 'in_progress')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    ticket_reference: Mapped[str] = mapped_column(String(32), nullable=False)
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
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    issue_description: Mapped[str] = mapped_column(Text, nullable=False)
    issue_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
