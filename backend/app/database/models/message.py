"""Conversation message database model."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


MESSAGE_ROLES = ("user", "assistant", "system", "tool")
MESSAGE_LANGUAGES = (
    "egyptian_arabic",
    "arabic",
    "franco_arabic",
    "english",
    "mixed",
    "unknown",
)


class Message(Base):
    """An ordered message belonging to a support conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_messages_conversation_id_sequence_number",
        ),
        CheckConstraint(f"role IN {MESSAGE_ROLES!r}", name="valid_role"),
        CheckConstraint(
            f"language IS NULL OR language IN {MESSAGE_LANGUAGES!r}",
            name="valid_language",
        ),
        CheckConstraint("sequence_number > 0", name="positive_sequence_number"),
        CheckConstraint("char_length(trim(content)) > 0", name="non_empty_content"),
        Index("ix_messages_conversation_id", "conversation_id"),
        Index("ix_messages_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
