"""AI model execution telemetry database model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


MODEL_RUN_PROVIDERS = ("gemini", "qwen", "fanar")
MODEL_RUN_STATUSES = ("running", "completed", "failed", "cancelled")


class ModelRun(Base):
    """One invocation of an AI model within a support conversation."""

    __tablename__ = "model_runs"
    __table_args__ = (
        CheckConstraint(
            f"provider IN {MODEL_RUN_PROVIDERS!r}", name="valid_provider"
        ),
        CheckConstraint(f"status IN {MODEL_RUN_STATUSES!r}", name="valid_status"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="non_negative_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="non_negative_output_tokens",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="non_negative_total_tokens",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="non_negative_latency_ms"
        ),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="non_negative_estimated_cost",
        ),
        CheckConstraint(
            "temperature IS NULL OR (temperature >= 0 AND temperature <= 2)",
            name="valid_temperature_range",
        ),
        CheckConstraint(
            "success = false OR error_message IS NULL",
            name="error_message_only_on_failure",
        ),
        Index("ix_model_runs_conversation_id", "conversation_id"),
        Index("ix_model_runs_provider", "provider"),
        Index("ix_model_runs_status", "status"),
        Index("ix_model_runs_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    temperature: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="model_runs")
