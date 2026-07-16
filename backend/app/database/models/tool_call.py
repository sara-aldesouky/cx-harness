"""Business-tool invocation audit model."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


TOOL_CALL_STATUSES = (
    "requested",
    "approved",
    "executing",
    "completed",
    "failed",
    "rejected",
)


class ToolCall(Base):
    """One business-tool request or execution within a model run."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint(
            f"status IN {TOOL_CALL_STATUSES!r}", name="valid_status"
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="non_negative_latency_ms",
        ),
        CheckConstraint(
            "success = false OR error_message IS NULL",
            name="error_message_only_on_failure",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= requested_at",
            name="started_at_not_before_requested_at",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= requested_at",
            name="finished_at_not_before_requested_at",
        ),
        CheckConstraint(
            "started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at",
            name="finished_at_not_before_started_at",
        ),
        Index("ix_tool_calls_model_run_id", "model_run_id"),
        Index("ix_tool_calls_tool_name", "tool_name"),
        Index("ix_tool_calls_status", "status"),
        Index("ix_tool_calls_requested_at", "requested_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    model_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("model_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    output_json: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSONB, nullable=True
    )
    success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    model_run: Mapped[ModelRun] = relationship(back_populates="tool_calls")
