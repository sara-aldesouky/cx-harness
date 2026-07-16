"""Model-run evaluation result database model."""

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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


EVALUATOR_TYPES = ("automatic", "human", "llm_judge")


class Evaluation(Base):
    """A partial or complete quality evaluation for one model run."""

    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint(
            "model_run_id",
            "evaluator_type",
            "evaluator_name",
            name="evaluator_identity",
        ),
        CheckConstraint(
            f"evaluator_type IN {EVALUATOR_TYPES!r}",
            name="valid_evaluator_type",
        ),
        CheckConstraint(
            "char_length(trim(evaluator_name)) > 0",
            name="non_empty_evaluator_name",
        ),
        CheckConstraint(
            "intent_score IS NULL OR "
            "(intent_score >= 0 AND intent_score <= 5)",
            name="valid_intent_score",
        ),
        CheckConstraint(
            "tool_score IS NULL OR (tool_score >= 0 AND tool_score <= 5)",
            name="valid_tool_score",
        ),
        CheckConstraint(
            "tone_score IS NULL OR (tone_score >= 0 AND tone_score <= 5)",
            name="valid_tone_score",
        ),
        CheckConstraint(
            "arabic_score IS NULL OR "
            "(arabic_score >= 0 AND arabic_score <= 5)",
            name="valid_arabic_score",
        ),
        CheckConstraint(
            "franco_score IS NULL OR "
            "(franco_score >= 0 AND franco_score <= 5)",
            name="valid_franco_score",
        ),
        CheckConstraint(
            "policy_score IS NULL OR "
            "(policy_score >= 0 AND policy_score <= 5)",
            name="valid_policy_score",
        ),
        CheckConstraint(
            "resolution_score IS NULL OR "
            "(resolution_score >= 0 AND resolution_score <= 5)",
            name="valid_resolution_score",
        ),
        CheckConstraint(
            "overall_score IS NULL OR "
            "(overall_score >= 0 AND overall_score <= 5)",
            name="valid_overall_score",
        ),
        CheckConstraint(
            "intent_score IS NOT NULL OR "
            "tool_score IS NOT NULL OR "
            "tone_score IS NOT NULL OR "
            "arabic_score IS NOT NULL OR "
            "franco_score IS NOT NULL OR "
            "policy_score IS NOT NULL OR "
            "resolution_score IS NOT NULL OR "
            "overall_score IS NOT NULL OR "
            "(notes IS NOT NULL AND char_length(trim(notes)) > 0) OR "
            "details_json IS NOT NULL",
            name="has_evaluation_content",
        ),
        Index("ix_evaluations_model_run_id", "model_run_id"),
        Index("ix_evaluations_evaluator_type", "evaluator_type"),
        Index("ix_evaluations_passed", "passed"),
        Index("ix_evaluations_evaluated_at", "evaluated_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    model_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("model_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    evaluator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluator_name: Mapped[str] = mapped_column(String(100), nullable=False)
    intent_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    tool_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    tone_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    arabic_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    franco_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    policy_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    resolution_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    overall_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details_json: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSONB, nullable=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    model_run: Mapped[ModelRun] = relationship(back_populates="evaluations")
