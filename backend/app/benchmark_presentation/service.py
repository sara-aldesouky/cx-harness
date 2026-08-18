"""Read-only Stage 16.4 facade over the frozen Stage 16.3 service."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.benchmark_presentation.contracts import BenchmarkCaseEvidence, BenchmarkRunListItem, BenchmarkRunPage
from app.benchmark_presentation.errors import InvalidScoringPolicyError
from app.benchmark_reporting.contracts import ScoringPolicy
from app.benchmark_reporting.repositories import BenchmarkReportingRepository
from app.benchmark_reporting.service import BenchmarkReportingService
from app.database.models.benchmark_analytics import (
    BenchmarkConversationResult,
    BenchmarkFailureEvent,
    BenchmarkMetricResult,
    BenchmarkRun,
    BenchmarkSuite,
    BenchmarkToolExecution,
)
from app.database.models.message import Message

DEFAULT_SCORING_POLICY = ScoringPolicy(
    policy_key="cx-deterministic-core",
    policy_version="1.0.0",
    metric_weights={
        "conversation_completion": Decimal(".30"),
        "tool_selection_match_rate": Decimal(".25"),
        "argument_validation_rate": Decimal(".15"),
        "grounding_enforcement_rate": Decimal(".20"),
        "continuity_resolution_rate": Decimal(".10"),
    },
)


class BenchmarkPresentationService:
    """Coordinates discovery and delegates every calculation to Stage 16.3."""

    def __init__(self, session: Session):
        self._session = session
        self._reporting = BenchmarkReportingService(BenchmarkReportingRepository(session))

    def list_runs(
        self,
        *,
        suite_key: Optional[str] = None,
        suite_version: Optional[str] = None,
        model_name: Optional[str] = None,
        provider_name: Optional[str] = None,
        status: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> BenchmarkRunPage:
        stored = func.count(BenchmarkConversationResult.id)
        passed = func.sum(func.cast(BenchmarkConversationResult.passed, Integer))
        stmt = (
            select(BenchmarkRun, BenchmarkSuite, stored.label("stored"), passed.label("passed"))
            .join(BenchmarkSuite)
            .outerjoin(BenchmarkConversationResult)
            .group_by(BenchmarkRun.id, BenchmarkSuite.id)
        )
        filters = []
        if suite_key:
            filters.append(BenchmarkSuite.suite_key == suite_key.strip().lower())
        if suite_version:
            filters.append(BenchmarkSuite.version == suite_version)
        if model_name:
            filters.append(BenchmarkRun.model_name == model_name)
        if provider_name:
            filters.append(BenchmarkRun.provider_name == provider_name)
        if status:
            filters.append(BenchmarkRun.status == status)
        if created_from:
            filters.append(BenchmarkRun.created_at >= created_from)
        if created_to:
            filters.append(BenchmarkRun.created_at <= created_to)
        stmt = stmt.where(*filters)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.execute(
            stmt.order_by(BenchmarkRun.created_at.desc(), BenchmarkRun.run_key, BenchmarkRun.id)
            .limit(limit)
            .offset(offset)
        ).all()
        items = []
        for run, suite, stored_count, passed_count in rows:
            items.append(
                BenchmarkRunListItem(
                    run_id=run.id,
                    run_key=run.run_key,
                    suite_key=suite.suite_key,
                    suite_version=suite.version,
                    suite_content_hash=suite.content_hash,
                    model_name=run.model_name,
                    provider_name=run.provider_name,
                    scoring_policy_key=DEFAULT_SCORING_POLICY.policy_key,
                    scoring_policy_version=DEFAULT_SCORING_POLICY.policy_version,
                    status=run.status,
                    expected_test_count=suite.test_case_count,
                    stored_test_count=stored_count,
                    completed_test_count=stored_count,
                    pass_rate=(Decimal(passed_count or 0) / Decimal(stored_count) if stored_count else None),
                    overall_score=None,
                    score_coverage=None,
                    created_at=run.created_at,
                    report_eligible=stored_count > 0,
                )
            )
        return BenchmarkRunPage(items=tuple(items), total=total, limit=limit, offset=offset)

    def policy(self, key: Optional[str], version: Optional[str]) -> ScoringPolicy:
        if key not in (None, DEFAULT_SCORING_POLICY.policy_key) or version not in (
            None,
            DEFAULT_SCORING_POLICY.policy_version,
        ):
            raise InvalidScoringPolicyError()
        return DEFAULT_SCORING_POLICY

    def get_report(self, run_id: UUID, policy: ScoringPolicy = DEFAULT_SCORING_POLICY):
        return self._reporting.generate_run_report(run_id, policy)

    def get_case_evidence(self, run_id: UUID) -> tuple[BenchmarkCaseEvidence, ...]:
        """Load export-only evidence without changing evaluation or scoring."""
        conversations = self._session.scalars(
            select(BenchmarkConversationResult)
            .where(BenchmarkConversationResult.benchmark_run_id == run_id)
            .order_by(BenchmarkConversationResult.test_case_key, BenchmarkConversationResult.id)
        ).all()
        model_name = self._session.scalar(select(BenchmarkRun.model_name).where(BenchmarkRun.id == run_id)) or "Unavailable"
        result_ids = tuple(result.id for result in conversations)
        conversation_ids = tuple(
            {result.source_conversation_id for result in conversations if result.source_conversation_id is not None}
        )
        messages_by_conversation: dict[UUID, list[Message]] = {}
        if conversation_ids:
            for message in self._session.scalars(
                select(Message)
                .where(Message.conversation_id.in_(conversation_ids))
                .order_by(Message.conversation_id, Message.sequence_number)
            ).all():
                messages_by_conversation.setdefault(message.conversation_id, []).append(message)
        tools_by_result: dict[UUID, list[BenchmarkToolExecution]] = {}
        metrics_by_result: dict[UUID, list[BenchmarkMetricResult]] = {}
        failures_by_result: dict[UUID, list[BenchmarkFailureEvent]] = {}
        if result_ids:
            for tool in self._session.scalars(
                select(BenchmarkToolExecution)
                .where(BenchmarkToolExecution.conversation_result_id.in_(result_ids))
                .order_by(BenchmarkToolExecution.conversation_result_id, BenchmarkToolExecution.execution_order)
            ).all():
                tools_by_result.setdefault(tool.conversation_result_id, []).append(tool)
            for metric in self._session.scalars(
                select(BenchmarkMetricResult)
                .where(BenchmarkMetricResult.conversation_result_id.in_(result_ids))
                .order_by(BenchmarkMetricResult.conversation_result_id, BenchmarkMetricResult.metric_key)
            ).all():
                metrics_by_result.setdefault(metric.conversation_result_id, []).append(metric)
            for failure in self._session.scalars(
                select(BenchmarkFailureEvent)
                .where(BenchmarkFailureEvent.conversation_result_id.in_(result_ids))
                .order_by(
                    BenchmarkFailureEvent.conversation_result_id,
                    BenchmarkFailureEvent.is_primary.desc(),
                    BenchmarkFailureEvent.created_at,
                )
            ).all():
                failures_by_result.setdefault(failure.conversation_result_id, []).append(failure)
        evidence = []
        for result in conversations:
            messages = messages_by_conversation.get(result.source_conversation_id, [])
            tools = tools_by_result.get(result.id, [])
            metrics = metrics_by_result.get(result.id, [])
            failures = failures_by_result.get(result.id, [])
            user_text = "\n\n".join(message.content for message in messages if message.role == "user")
            assistant_text = "\n\n".join(message.content for message in messages if message.role == "assistant")
            evaluation_scores = {metric.metric_key: str(metric.normalized_score if metric.normalized_score is not None else metric.value_boolean if metric.value_boolean is not None else metric.value_numeric if metric.value_numeric is not None else metric.value_text) for metric in metrics}
            evidence.append(BenchmarkCaseEvidence(
                test_case_id=result.test_case_key, language=result.language, category=result.category,
                customer_question=user_text or "Not available", model=model_name,
                model_response=assistant_text or "Not available", passed=result.passed,
                hallucination=result.hallucination_detected, grounded=not result.grounding_failure_detected,
                correct_tool=(all(tool.selection_correct for tool in tools) if tools else None),
                tool_used=tuple(tool.tool_name for tool in tools),
                intent_match=(result.actual_intent == result.expected_intent if result.actual_intent is not None else None),
                latency_ms=result.total_latency_ms, tokens=result.total_tokens, cost=result.estimated_cost,
                currency_code=result.currency_code, failure_category=result.failure_category,
                failure_explanation=(failures[0].description if failures else None),
                evaluation_scores=evaluation_scores,
                tool_calls=tuple({"tool": tool.tool_name, "arguments": tool.sanitized_arguments, "successful": tool.execution_successful, "failure_code": tool.failure_code} for tool in tools),
                raw_metadata={"expected_intent": result.expected_intent, "actual_intent": result.actual_intent, "final_outcome": result.final_outcome},
            ))
        return tuple(evidence)

    def compare(self, run_ids: tuple[UUID, ...], policy: ScoringPolicy = DEFAULT_SCORING_POLICY):
        return self._reporting.compare_runs(tuple(sorted(run_ids, key=str)), policy)
