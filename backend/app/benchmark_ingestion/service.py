"""Application service for atomic, idempotent benchmark analytics ingestion."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.benchmark_analytics.contracts import (
    BenchmarkRunDefinition, BenchmarkRunSummary, FinalOutcome, RunStatus,
)
from app.benchmark_analytics.repositories import (
    BenchmarkConversationResultRepository, BenchmarkFailureRepository,
    BenchmarkMetricRepository, BenchmarkProviderTurnRepository,
    BenchmarkRunRepository, BenchmarkSuiteRepository,
    BenchmarkToolExecutionRepository,
)
from app.benchmark_ingestion.contracts import (
    BenchmarkExecutionIngestionRequest, BenchmarkIngestionSummary,
    BenchmarkRunIdentity, CompletedConversationExecution,
    ConversationIngestionResult, IngestionItemStatus, IngestionResult,
)
from app.benchmark_ingestion.costing import BenchmarkCostCalculator
from app.benchmark_ingestion.errors import (
    BenchmarkIngestionError, IngestionConflictError, IngestionLifecycleError,
    IngestionRepositoryError, IngestionTransactionError, IngestionValidationError,
    IncompleteRunError,
)
from app.benchmark_ingestion.mappers import (
    map_conversation, map_failures, map_metrics, map_tools, map_turns,
)
from app.database.models.benchmark_analytics import BenchmarkConversationResult


logger = logging.getLogger(__name__)


class BenchmarkIngestionService:
    """Coordinates ingestion; it never executes providers, tools, or business writes."""

    def __init__(
        self, session: Session, *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        cost_calculator: Optional[BenchmarkCostCalculator] = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._costs = cost_calculator or BenchmarkCostCalculator()
        self._suites = BenchmarkSuiteRepository(session)
        self._runs = BenchmarkRunRepository(session)
        self._conversations = BenchmarkConversationResultRepository(session)
        self._turns = BenchmarkProviderTurnRepository(session)
        self._tools = BenchmarkToolExecutionRepository(session)
        self._metrics = BenchmarkMetricRepository(session)
        self._failures = BenchmarkFailureRepository(session)

    def create_run(self, identity: BenchmarkRunIdentity) -> BenchmarkRunDefinition:
        suite = self._suites.get_by_key_version(identity.suite_key, identity.suite_version)
        if suite is None:
            raise IngestionValidationError("benchmark suite identity is unknown")
        existing = self._runs.get_by_run_key(identity.run_key)
        if existing is not None:
            self._assert_run_identity(existing, suite.id, identity)
            return existing
        now = self._clock()
        definition = BenchmarkRunDefinition(
            run_key=identity.run_key, benchmark_suite_id=suite.id,
            model_name=identity.model_name, model_version=identity.model_version,
            provider_name=identity.provider_name, provider_type=identity.provider_type,
            deployment_mode=identity.deployment_mode,
            configuration_snapshot=identity.configuration_snapshot,
            pricing_snapshot=identity.pricing_snapshot, created_at=now, updated_at=now,
        )
        try:
            created = self._runs.create(definition)
            logger.info("benchmark ingestion run created", extra={"run_key": identity.run_key})
            return created
        except SQLAlchemyError as exc:
            raise IngestionRepositoryError("unable to create benchmark run") from exc

    def start_run(self, run_id):
        try:
            return self._runs.mark_running(run_id, self._clock())
        except (LookupError, ValueError) as exc:
            raise IngestionLifecycleError(str(exc)) from exc

    def ingest_request(self, request: BenchmarkExecutionIngestionRequest) -> IngestionResult:
        run = self.create_run(request.identity)
        if run.status is RunStatus.CREATED:
            run = self.start_run(run.id)
        items = self.ingest_batch(run.id, request.conversations)
        return IngestionResult(benchmark_run_id=run.id, items=items)

    def ingest_batch(self, run_id, conversations: Iterable[CompletedConversationExecution]):
        return tuple(self._ingest_safely(run_id, item) for item in conversations)

    def _ingest_safely(self, run_id, execution):
        try:
            return self.ingest_conversation(run_id, execution)
        except BenchmarkIngestionError as exc:
            logger.warning("benchmark conversation ingestion failed", extra={"error_code": exc.code})
            return ConversationIngestionResult(
                test_case_key=execution.test_case_key, status=IngestionItemStatus.FAILED,
                error_code=exc.code,
            )

    def ingest_conversation(self, run_id, execution: CompletedConversationExecution):
        run = self._runs.get_by_id(run_id)
        if run is None:
            raise IngestionLifecycleError("benchmark run not found")
        existing = self._conversations.get_by_run_case(run_id, execution.test_case_key)
        now = self._clock()
        cost = self._costs.calculate(
            run.pricing_snapshot,
            sum(t.usage.input_tokens for t in execution.provider_turns),
            sum(t.usage.output_tokens for t in execution.provider_turns),
            len(execution.provider_turns), run.deployment_mode,
        )
        candidate = map_conversation(execution, run_id, cost, now)
        turns, turn_ids = map_turns(execution, candidate.id)
        tools, tool_ids = map_tools(execution, candidate.id, turn_ids)
        metrics = map_metrics(execution, candidate, cost, now)
        failures = map_failures(execution, candidate.id, turn_ids, tool_ids, now)
        replace_partial = False
        if existing is not None:
            existing_children = (
                self._turns.list_in_order(existing.id),
                self._tools.list_by_conversation(existing.id),
                self._metrics.list_by_conversation(existing.id),
                self._failures.list_by_conversation(existing.id),
            )
            expected_counts = (len(turns), len(tools), len(metrics), len(failures))
            actual_counts = tuple(len(items) for items in existing_children)
            replace_partial = actual_counts != expected_counts
            if not replace_partial and self._equivalent(
                existing, candidate, existing_children, (turns, tools, metrics, failures)
            ):
                logger.info("benchmark ingestion idempotent no-op")
                return ConversationIngestionResult(
                    test_case_key=execution.test_case_key, status=IngestionItemStatus.IDEMPOTENT,
                    conversation_result_id=existing.id,
                )
            if not replace_partial:
                raise IngestionConflictError("test-case identity already exists with different content")
        if run.status is not RunStatus.RUNNING:
            raise IngestionLifecycleError("conversations may only be ingested into running runs")
        logger.info("benchmark conversation ingestion started")
        try:
            with self._session.begin_nested():
                if replace_partial:
                    row = self._session.get(BenchmarkConversationResult, existing.id)
                    self._session.delete(row)
                    self._session.flush()
                self._conversations.insert(candidate)
                self._turns.bulk_insert(turns)
                self._tools.bulk_insert(tools)
                self._metrics.bulk_insert(metrics)
                self._failures.bulk_insert(failures)
        except BenchmarkIngestionError:
            raise
        except SQLAlchemyError as exc:
            logger.error("benchmark conversation ingestion rolled back")
            raise IngestionTransactionError("atomic conversation persistence failed") from exc
        except Exception as exc:
            logger.error("benchmark conversation ingestion rolled back")
            raise IngestionRepositoryError("analytics repository operation failed") from exc
        logger.info("benchmark conversation ingestion succeeded")
        return ConversationIngestionResult(
            test_case_key=execution.test_case_key, status=IngestionItemStatus.INGESTED,
            conversation_result_id=candidate.id,
        )

    def retry_failed_item(self, run_id, execution):
        return self.ingest_conversation(run_id, execution)

    def get_ingestion_status(self, run_id) -> BenchmarkRunSummary:
        rows = self._conversations.list_by_run(run_id)
        self._validate_child_sets(rows)
        if self._runs.get_by_id(run_id) is None:
            raise IngestionLifecycleError("benchmark run not found")
        return self._summary(run_id, rows)

    def _validate_child_sets(self, rows):
        for row in rows:
            if len(self._turns.list_in_order(row.id)) != row.provider_turn_count:
                raise IncompleteRunError("provider-turn child set is incomplete")
            if len(self._tools.list_by_conversation(row.id)) != row.tool_execution_count:
                raise IncompleteRunError("tool-execution child set is incomplete")
            if not self._metrics.list_by_conversation(row.id):
                raise IncompleteRunError("deterministic metric child set is incomplete")

    def finalize_run(self, run_id) -> BenchmarkIngestionSummary:
        run = self._runs.get_by_id(run_id)
        if run is None or run.status is not RunStatus.RUNNING:
            raise IngestionLifecycleError("only running benchmark runs may be finalized")
        suite = self._suites.get_by_id(run.benchmark_suite_id)
        if suite is None:
            raise IngestionLifecycleError("benchmark suite not found")
        rows = self._conversations.list_by_run(run_id)
        self._validate_child_sets(rows)
        if not rows:
            self._runs.mark_failed(run_id, self._clock())
            status = RunStatus.FAILED
        elif len(rows) < suite.test_case_count:
            self._runs.mark_partially_completed(run_id, self._clock())
            status = RunStatus.PARTIALLY_COMPLETED
        elif len(rows) == suite.test_case_count:
            self._runs.mark_completed(run_id, self._clock())
            status = RunStatus.COMPLETED
        else:
            raise IngestionValidationError("ingested conversations exceed suite test count")
        summary = self._summary(run_id, rows)
        failure_sets = [self._failures.list_by_conversation(row.id) for row in rows]
        has_category = lambda category: sum(any(item.failure_category.value == category for item in items) for items in failure_sets)
        has_layer = lambda layers: sum(any(item.responsibility_layer.value in layers for item in items) for items in failure_sets)
        logger.info("benchmark ingestion run finalized", extra={"status": status.value})
        return BenchmarkIngestionSummary(
            benchmark_run_id=run_id, expected_test_case_count=suite.test_case_count,
            ingested_conversation_count=len(rows), benchmark_pass_count=summary.passed_count,
            benchmark_fail_count=summary.failed_count + summary.degraded_count,
            total_provider_turns=summary.provider_turn_count,
            total_tool_executions=summary.tool_execution_count,
            total_input_tokens=summary.input_tokens, total_output_tokens=summary.output_tokens,
            total_tokens=summary.input_tokens + summary.output_tokens,
            total_latency_ms=summary.total_latency_ms,
            total_estimated_cost=summary.estimated_cost,
            conversations_with_business_data_failures=has_category("business_data"),
            conversations_with_model_failures=has_layer({"model"}),
            conversations_with_infrastructure_failures=has_layer({"provider","harness","evaluation_pipeline"}),
            conversations_with_security_failures=has_layer({"security"}),
            finalized_status=status.value,
        )

    def _summary(self, run_id, rows):
        costs = [row.estimated_cost for row in rows if row.estimated_cost is not None]
        currencies = {row.currency_code for row in rows if row.currency_code is not None}
        if len(currencies) > 1:
            raise IngestionValidationError("run contains mixed currencies")
        return BenchmarkRunSummary(
            benchmark_run_id=run_id, conversation_count=len(rows),
            passed_count=sum(row.final_outcome is FinalOutcome.PASSED for row in rows),
            failed_count=sum(row.final_outcome in {FinalOutcome.FAILED, FinalOutcome.INFRASTRUCTURE_FAILURE, FinalOutcome.CANCELLED} for row in rows),
            degraded_count=sum(row.final_outcome is FinalOutcome.DEGRADED for row in rows),
            provider_turn_count=sum(row.provider_turn_count for row in rows),
            tool_execution_count=sum(row.tool_execution_count for row in rows),
            successful_tool_execution_count=sum(row.successful_tool_execution_count for row in rows),
            input_tokens=sum(row.input_tokens for row in rows), output_tokens=sum(row.output_tokens for row in rows),
            total_latency_ms=sum((row.total_latency_ms for row in rows), Decimal("0")),
            estimated_cost=sum(costs, Decimal("0")) if costs and len(costs) == len(rows) else None,
            currency_code=next(iter(currencies)) if costs and len(costs) == len(rows) else None,
        )

    def _equivalent(self, existing, candidate, existing_children, candidate_children):
        fields = set(type(existing).model_fields) - {"id", "created_at"}
        parent_equal = all(getattr(existing, name) == getattr(candidate, name) for name in fields)
        if not parent_equal: return False
        excluded = {
            "id", "conversation_result_id", "provider_turn_id", "tool_execution_id",
            "created_at",
        }
        for stored_group, candidate_group in zip(existing_children, candidate_children):
            def canonical(value):
                if isinstance(value, Decimal):
                    return value.normalize()
                if isinstance(value, dict):
                    return {key: canonical(nested) for key, nested in value.items()}
                if isinstance(value, (list, tuple)):
                    return tuple(canonical(nested) for nested in value)
                return value
            def signatures(items):
                return sorted(
                    repr(canonical(item.model_dump(mode="python", exclude=excluded))) for item in items
                )
            if signatures(stored_group) != signatures(candidate_group):
                return False
        return True

    @staticmethod
    def _assert_run_identity(run, suite_id, identity):
        actual = (
            run.benchmark_suite_id, run.model_name, run.model_version, run.provider_name,
            run.provider_type, run.deployment_mode, run.configuration_snapshot,
            run.pricing_snapshot,
        )
        expected = (
            suite_id, identity.model_name, identity.model_version, identity.provider_name,
            identity.provider_type, identity.deployment_mode, identity.configuration_snapshot,
            identity.pricing_snapshot,
        )
        if actual != expected:
            raise IngestionConflictError("run identity or immutable snapshots conflict")
