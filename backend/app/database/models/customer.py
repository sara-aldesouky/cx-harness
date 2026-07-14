"""Customer database model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint, func, true
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Customer(Base):
    """A customer who can place commerce orders."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("phone", name="uq_customers_phone"),
        UniqueConstraint("email", name="uq_customers_email"),
        Index("ix_customers_phone", "phone"),
        Index("ix_customers_email", "email"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    preferred_language: Mapped[str] = mapped_column(
        String(16), nullable=False, default="en", server_default="en"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
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

    orders: Mapped[list[Order]] = relationship(
        back_populates="customer", passive_deletes=True
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="customer", passive_deletes=True
    )
