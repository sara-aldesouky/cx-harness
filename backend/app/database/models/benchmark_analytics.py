"""Isolated relational source of truth for benchmark analytics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class BenchmarkSuite(Base):
    __tablename__ = "benchmark_suites"
    __table_args__ = (
        UniqueConstraint("suite_key", "version", name="uq_benchmark_suites_key_version"),
        CheckConstraint("test_case_count > 0", name="positive_test_case_count"),
        CheckConstraint("status IN ('draft','validated','frozen','archived')", name="valid_status"),
        Index("ix_benchmark_suites_status", "status"),
        Index("ix_benchmark_suites_created_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    suite_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    test_case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    runs: Mapped[list["BenchmarkRun"]] = relationship(back_populates="suite", passive_deletes=True)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_benchmark_runs_run_key"),
        CheckConstraint("status IN ('created','running','completed','partially_completed','failed','cancelled')", name="valid_status"),
        CheckConstraint("provider_type IN ('local_runtime','api','self_hosted')", name="valid_provider_type"),
        CheckConstraint("deployment_mode IN ('local','self_hosted','managed_api','hybrid')", name="valid_deployment_mode"),
        Index("ix_benchmark_runs_suite", "benchmark_suite_id"),
        Index("ix_benchmark_runs_status", "status"),
        Index("ix_benchmark_runs_model_name", "model_name"),
        Index("ix_benchmark_runs_provider_name", "provider_name"),
        Index("ix_benchmark_runs_created_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_key: Mapped[str] = mapped_column(String(128), nullable=False)
    benchmark_suite_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_suites.id", ondelete="RESTRICT"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[Optional[str]] = mapped_column(String(100))
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    deployment_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pricing_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    suite: Mapped[BenchmarkSuite] = relationship(back_populates="runs")
    conversation_results: Mapped[list["BenchmarkConversationResult"]] = relationship(back_populates="run", cascade="all, delete-orphan", passive_deletes=True)


class BenchmarkConversationResult(Base):
    __tablename__ = "benchmark_conversation_results"
    __table_args__ = (
        UniqueConstraint("benchmark_run_id", "test_case_key", name="uq_benchmark_conversation_results_run_case"),
        CheckConstraint("provider_turn_count >= 0 AND customer_turn_count >= 0 AND clarification_count >= 0", name="non_negative_turn_counts"),
        CheckConstraint("tool_execution_count >= 0 AND successful_tool_execution_count >= 0 AND failed_tool_execution_count >= 0", name="non_negative_tool_counts"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0", name="non_negative_tokens"),
        CheckConstraint("total_latency_ms >= 0", name="non_negative_latency"),
        CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="non_negative_cost"),
        CheckConstraint("final_outcome IN ('passed','failed','degraded','cancelled','infrastructure_failure')", name="valid_final_outcome"),
        Index("ix_benchmark_conversation_results_run", "benchmark_run_id"),
        Index("ix_benchmark_conversation_results_test_case", "test_case_key"),
        Index("ix_benchmark_conversation_results_language", "language"),
        Index("ix_benchmark_conversation_results_category", "category"),
        Index("ix_benchmark_conversation_results_outcome", "final_outcome"),
        Index("ix_benchmark_conversation_results_failure_category", "failure_category"),
        Index("ix_benchmark_conversation_results_created_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    benchmark_run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False)
    test_case_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_conversation_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True))
    language: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    complexity_level: Mapped[Optional[str]] = mapped_column(String(32))
    pressure_level: Mapped[Optional[str]] = mapped_column(String(32))
    expected_intent: Mapped[str] = mapped_column(Text, nullable=False)
    actual_intent: Mapped[Optional[str]] = mapped_column(Text)
    final_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_category: Mapped[Optional[str]] = mapped_column(String(64))
    provider_turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    customer_turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clarification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful_tool_execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tool_execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hallucination_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grounding_failure_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    infrastructure_failure_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_latency_ms: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    estimated_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8))
    currency_code: Mapped[Optional[str]] = mapped_column(String(3))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    run: Mapped[BenchmarkRun] = relationship(back_populates="conversation_results")
    provider_turns: Mapped[list["BenchmarkProviderTurn"]] = relationship(back_populates="conversation_result", cascade="all, delete-orphan", passive_deletes=True)
    tool_executions: Mapped[list["BenchmarkToolExecution"]] = relationship(back_populates="conversation_result", cascade="all, delete-orphan", passive_deletes=True)
    metric_results: Mapped[list["BenchmarkMetricResult"]] = relationship(back_populates="conversation_result", cascade="all, delete-orphan", passive_deletes=True)
    failure_events: Mapped[list["BenchmarkFailureEvent"]] = relationship(back_populates="conversation_result", cascade="all, delete-orphan", passive_deletes=True)


class BenchmarkProviderTurn(Base):
    __tablename__ = "benchmark_provider_turns"
    __table_args__ = (
        UniqueConstraint("conversation_result_id", "turn_number", name="uq_benchmark_provider_turns_result_turn"),
        CheckConstraint("turn_number > 0 AND input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0 AND latency_ms >= 0", name="valid_turn_measurements"),
        Index("ix_benchmark_provider_turns_result", "conversation_result_id"),
        Index("ix_benchmark_provider_turns_created_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_result_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_conversation_results.id", ondelete="CASCADE"), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_request_id: Mapped[Optional[str]] = mapped_column(String(200))
    finish_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    context_tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    context_window_limit: Mapped[Optional[int]] = mapped_column(Integer)
    context_utilization_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 6))
    response_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    request_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    response_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    conversation_result: Mapped[BenchmarkConversationResult] = relationship(back_populates="provider_turns")


class BenchmarkToolExecution(Base):
    __tablename__ = "benchmark_tool_executions"
    __table_args__ = (
        UniqueConstraint("conversation_result_id", "execution_order", name="uq_benchmark_tool_executions_result_order"),
        CheckConstraint("execution_order > 0 AND latency_ms >= 0", name="valid_execution_measurements"),
        Index("ix_benchmark_tool_executions_result", "conversation_result_id"),
        Index("ix_benchmark_tool_executions_tool_name", "tool_name"),
        Index("ix_benchmark_tool_executions_created_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_result_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_conversation_results.id", ondelete="CASCADE"), nullable=False)
    provider_turn_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_provider_turns.id", ondelete="SET NULL"))
    execution_order: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_tool: Mapped[Optional[str]] = mapped_column(String(128))
    selection_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    arguments_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    authorization_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    execution_successful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    business_failure: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_code: Mapped[Optional[str]] = mapped_column(String(128))
    latency_ms: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False, default=0)
    sanitized_arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sanitized_result_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    conversation_result: Mapped[BenchmarkConversationResult] = relationship(back_populates="tool_executions")


class BenchmarkMetricResult(Base):
    __tablename__ = "benchmark_metric_results"
    __table_args__ = (
        CheckConstraint("((value_numeric IS NOT NULL)::int + (value_boolean IS NOT NULL)::int + (value_text IS NOT NULL)::int) = 1", name="exactly_one_metric_value"),
        CheckConstraint("normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <= 1)", name="valid_normalized_score"),
        CheckConstraint("evaluation_method IN ('deterministic_rule','automated_evaluator','model_judged','human_review','imported_annotation')", name="valid_evaluation_method"),
        UniqueConstraint("conversation_result_id", "metric_key", "metric_version", "evaluation_method", "evaluator_name", "evaluator_version", name="uq_benchmark_metric_results_definition"),
        Index("ix_benchmark_metric_results_conversation", "conversation_result_id"),
        Index("ix_benchmark_metric_results_metric_key", "metric_key"),
        Index("ix_benchmark_metric_results_created_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_result_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_conversation_results.id", ondelete="CASCADE"), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(64), nullable=False)
    value_numeric: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8))
    value_boolean: Mapped[Optional[bool]] = mapped_column(Boolean)
    value_text: Mapped[Optional[str]] = mapped_column(Text)
    maximum_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8))
    normalized_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 10))
    evaluation_method: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    conversation_result: Mapped[BenchmarkConversationResult] = relationship(back_populates="metric_results")


class BenchmarkFailureEvent(Base):
    __tablename__ = "benchmark_failure_events"
    __table_args__ = (
        Index("ix_benchmark_failure_events_conversation", "conversation_result_id"),
        Index("ix_benchmark_failure_events_category", "failure_category"),
        Index("ix_benchmark_failure_events_responsibility", "responsibility_layer"),
        Index("ix_benchmark_failure_events_created_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_result_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_conversation_results.id", ondelete="CASCADE"), nullable=False)
    provider_turn_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_provider_turns.id", ondelete="SET NULL"))
    tool_execution_id: Mapped[Optional[UUID]] = mapped_column(PostgreSQLUUID(as_uuid=True), ForeignKey("benchmark_tool_executions.id", ondelete="SET NULL"))
    failure_category: Mapped[str] = mapped_column(String(64), nullable=False)
    failure_code: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsibility_layer: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    conversation_result: Mapped[BenchmarkConversationResult] = relationship(back_populates="failure_events")
