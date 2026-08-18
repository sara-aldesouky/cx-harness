"""Persistence boundaries for the isolated benchmark analytics subsystem."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.benchmark_analytics.contracts import (
    BenchmarkRunDefinition, BenchmarkSuiteDefinition, ConversationResultRecord,
    FailureEventRecord, FinalOutcome, MetricResultRecord, ProviderTurnRecord,
    RunStatus, SuiteStatus, ToolExecutionRecord,
)
from app.database.models.benchmark_analytics import (
    BenchmarkConversationResult, BenchmarkFailureEvent, BenchmarkMetricResult,
    BenchmarkProviderTurn, BenchmarkRun, BenchmarkSuite, BenchmarkToolExecution,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _suite(row: BenchmarkSuite) -> BenchmarkSuiteDefinition:
    return BenchmarkSuiteDefinition.model_validate({c.name: getattr(row, c.name) for c in row.__table__.columns})


def _run(row: BenchmarkRun) -> BenchmarkRunDefinition:
    return BenchmarkRunDefinition.model_validate({c.name: getattr(row, c.name) for c in row.__table__.columns})


def _conversation(row: BenchmarkConversationResult) -> ConversationResultRecord:
    return ConversationResultRecord.model_validate({c.name: getattr(row, c.name) for c in row.__table__.columns})


def _turn(row: BenchmarkProviderTurn) -> ProviderTurnRecord:
    return ProviderTurnRecord.model_validate({c.name: getattr(row, c.name) for c in row.__table__.columns})


def _tool(row: BenchmarkToolExecution) -> ToolExecutionRecord:
    return ToolExecutionRecord.model_validate({c.name: getattr(row, c.name) for c in row.__table__.columns})


def _metric(row: BenchmarkMetricResult) -> MetricResultRecord:
    return MetricResultRecord.model_validate({c.name: getattr(row, c.name) for c in row.__table__.columns})


def _failure(row: BenchmarkFailureEvent) -> FailureEventRecord:
    return FailureEventRecord.model_validate({c.name: getattr(row, c.name) for c in row.__table__.columns})


def _payload(contract, *, exclude=()):
    data = contract.model_dump(mode="python")
    for key in exclude:
        data.pop(key, None)
    return data


class BenchmarkSuiteRepository:
    def __init__(self, session: Session): self._session = session

    def create(self, definition: BenchmarkSuiteDefinition) -> BenchmarkSuiteDefinition:
        row = BenchmarkSuite(**_payload(definition))
        self._session.add(row); self._session.flush()
        return _suite(row)

    def get_by_id(self, suite_id: UUID) -> Optional[BenchmarkSuiteDefinition]:
        row = self._session.get(BenchmarkSuite, suite_id)
        return None if row is None else _suite(row)

    def get_by_key_version(self, suite_key: str, version: str) -> Optional[BenchmarkSuiteDefinition]:
        row = self._session.scalar(select(BenchmarkSuite).where(BenchmarkSuite.suite_key == suite_key.strip().lower(), BenchmarkSuite.version == version.strip()))
        return None if row is None else _suite(row)

    def list(self) -> tuple[BenchmarkSuiteDefinition, ...]:
        rows = self._session.scalars(select(BenchmarkSuite).order_by(BenchmarkSuite.suite_key, BenchmarkSuite.version, BenchmarkSuite.id)).all()
        return tuple(_suite(row) for row in rows)

    def freeze(self, suite_id: UUID) -> BenchmarkSuiteDefinition:
        return self._set_status(suite_id, SuiteStatus.FROZEN)

    def archive(self, suite_id: UUID) -> BenchmarkSuiteDefinition:
        return self._set_status(suite_id, SuiteStatus.ARCHIVED)

    def delete(self, suite_id: UUID) -> bool:
        row = self._session.get(BenchmarkSuite, suite_id)
        if row is None: return False
        self._session.delete(row); self._session.flush(); return True

    def _set_status(self, suite_id: UUID, status: SuiteStatus):
        row = self._session.get(BenchmarkSuite, suite_id)
        if row is None: raise LookupError("benchmark suite not found")
        if row.status == SuiteStatus.ARCHIVED.value:
            raise ValueError("archived benchmark suites cannot transition")
        row.status = status.value; row.updated_at = _now(); self._session.flush()
        return _suite(row)


class BenchmarkRunRepository:
    _TERMINAL = {RunStatus.COMPLETED, RunStatus.PARTIALLY_COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    def __init__(self, session: Session): self._session = session

    def create(self, definition: BenchmarkRunDefinition) -> BenchmarkRunDefinition:
        data = _payload(definition)
        data["configuration_snapshot"] = definition.configuration_snapshot.model_dump(mode="json")
        data["pricing_snapshot"] = definition.pricing_snapshot.model_dump(mode="json")
        row = BenchmarkRun(**data); self._session.add(row); self._session.flush(); return _run(row)

    def mark_running(self, run_id: UUID, at: Optional[datetime] = None): return self._transition(run_id, RunStatus.RUNNING, at)
    def mark_completed(self, run_id: UUID, at: Optional[datetime] = None): return self._transition(run_id, RunStatus.COMPLETED, at)
    def mark_partially_completed(self, run_id: UUID, at: Optional[datetime] = None): return self._transition(run_id, RunStatus.PARTIALLY_COMPLETED, at)
    def mark_failed(self, run_id: UUID, at: Optional[datetime] = None): return self._transition(run_id, RunStatus.FAILED, at)

    def _transition(self, run_id, status, at):
        row = self._session.get(BenchmarkRun, run_id)
        if row is None: raise LookupError("benchmark run not found")
        if row.status in {item.value for item in self._TERMINAL}: raise ValueError("terminal benchmark run cannot transition")
        timestamp = at or _now()
        if timestamp.tzinfo is None: raise ValueError("lifecycle timestamp must be timezone-aware")
        if status is RunStatus.RUNNING:
            if row.status != RunStatus.CREATED.value: raise ValueError("only created runs may start")
            row.started_at = timestamp
        else:
            if row.status != RunStatus.RUNNING.value: raise ValueError("only running runs may complete")
            row.completed_at = timestamp
        row.status = status.value; row.updated_at = timestamp; self._session.flush(); return _run(row)

    def get_by_id(self, run_id):
        row = self._session.get(BenchmarkRun, run_id); return None if row is None else _run(row)
    def get_by_run_key(self, run_key):
        row = self._session.scalar(select(BenchmarkRun).where(BenchmarkRun.run_key == run_key)); return None if row is None else _run(row)
    def list_by_suite(self, suite_id): return self._list(BenchmarkRun.benchmark_suite_id == suite_id)
    def list_by_model(self, model_name): return self._list(BenchmarkRun.model_name == model_name)
    def delete(self, run_id):
        result = self._session.execute(delete(BenchmarkRun).where(BenchmarkRun.id == run_id)); self._session.flush(); return bool(result.rowcount)
    def _list(self, criterion):
        rows = self._session.scalars(select(BenchmarkRun).where(criterion).order_by(BenchmarkRun.created_at, BenchmarkRun.id)).all()
        return tuple(_run(row) for row in rows)


class BenchmarkConversationResultRepository:
    def __init__(self, session: Session): self._session = session
    def insert(self, record): return self.bulk_insert((record,))[0]
    def bulk_insert(self, records: Iterable[ConversationResultRecord]):
        rows = [BenchmarkConversationResult(**_payload(record)) for record in records]
        self._session.add_all(rows); self._session.flush(); return tuple(_conversation(row) for row in rows)
    def get_by_run_case(self, run_id, test_case_key):
        row = self._session.scalar(select(BenchmarkConversationResult).where(BenchmarkConversationResult.benchmark_run_id == run_id, BenchmarkConversationResult.test_case_key == test_case_key)); return None if row is None else _conversation(row)
    def list_by_run(self, run_id): return self._list(BenchmarkConversationResult.benchmark_run_id == run_id)
    def filter_by_language(self, run_id, language): return self._list(BenchmarkConversationResult.benchmark_run_id == run_id, BenchmarkConversationResult.language == language)
    def filter_by_category(self, run_id, category): return self._list(BenchmarkConversationResult.benchmark_run_id == run_id, BenchmarkConversationResult.category == category)
    def filter_by_result(self, run_id, outcome: FinalOutcome): return self._list(BenchmarkConversationResult.benchmark_run_id == run_id, BenchmarkConversationResult.final_outcome == outcome.value)
    def count_by_status(self, run_id):
        rows = self._session.execute(select(BenchmarkConversationResult.final_outcome, func.count()).where(BenchmarkConversationResult.benchmark_run_id == run_id).group_by(BenchmarkConversationResult.final_outcome)).all()
        return {outcome: count for outcome, count in rows}
    def _list(self, *criteria):
        rows = self._session.scalars(select(BenchmarkConversationResult).where(*criteria).order_by(BenchmarkConversationResult.test_case_key, BenchmarkConversationResult.id)).all()
        return tuple(_conversation(row) for row in rows)


class BenchmarkProviderTurnRepository:
    def __init__(self, session): self._session = session
    def insert(self, record): return self.bulk_insert((record,))[0]
    def bulk_insert(self, records):
        rows = [BenchmarkProviderTurn(**_payload(record)) for record in records]; self._session.add_all(rows); self._session.flush(); return tuple(_turn(row) for row in rows)
    def list_in_order(self, conversation_result_id):
        rows = self._session.scalars(select(BenchmarkProviderTurn).where(BenchmarkProviderTurn.conversation_result_id == conversation_result_id).order_by(BenchmarkProviderTurn.turn_number, BenchmarkProviderTurn.id)).all(); return tuple(_turn(row) for row in rows)
    def list_by_run(self, run_id):
        rows = self._session.scalars(
            select(BenchmarkProviderTurn)
            .join(BenchmarkConversationResult)
            .where(BenchmarkConversationResult.benchmark_run_id == run_id)
            .order_by(
                BenchmarkConversationResult.test_case_key,
                BenchmarkProviderTurn.turn_number,
                BenchmarkProviderTurn.id,
            )
        ).all()
        return tuple(_turn(row) for row in rows)


class BenchmarkToolExecutionRepository:
    def __init__(self, session): self._session = session
    def insert(self, record): return self.bulk_insert((record,))[0]
    def bulk_insert(self, records):
        rows = [BenchmarkToolExecution(**_payload(record)) for record in records]; self._session.add_all(rows); self._session.flush(); return tuple(_tool(row) for row in rows)
    def list_by_conversation(self, conversation_result_id):
        rows = self._session.scalars(select(BenchmarkToolExecution).where(BenchmarkToolExecution.conversation_result_id == conversation_result_id).order_by(BenchmarkToolExecution.execution_order, BenchmarkToolExecution.id)).all(); return tuple(_tool(row) for row in rows)
    def list_by_run(self, run_id):
        rows = self._session.scalars(
            select(BenchmarkToolExecution)
            .join(BenchmarkConversationResult)
            .where(BenchmarkConversationResult.benchmark_run_id == run_id)
            .order_by(
                BenchmarkConversationResult.test_case_key,
                BenchmarkToolExecution.execution_order,
                BenchmarkToolExecution.id,
            )
        ).all()
        return tuple(_tool(row) for row in rows)
    def aggregate_by_tool_name(self, run_id):
        rows = self._session.execute(select(BenchmarkToolExecution.tool_name, func.count()).join(BenchmarkConversationResult).where(BenchmarkConversationResult.benchmark_run_id == run_id).group_by(BenchmarkToolExecution.tool_name).order_by(BenchmarkToolExecution.tool_name)).all(); return {name: count for name, count in rows}
    def aggregate_success_failure(self, run_id):
        rows = self._session.execute(select(BenchmarkToolExecution.execution_successful, func.count()).join(BenchmarkConversationResult).where(BenchmarkConversationResult.benchmark_run_id == run_id).group_by(BenchmarkToolExecution.execution_successful)).all(); return {("successful" if success else "failed"): count for success, count in rows}


class BenchmarkMetricRepository:
    def __init__(self, session): self._session = session
    def insert(self, record): return self.bulk_insert((record,))[0]
    def bulk_insert(self, records):
        rows = [BenchmarkMetricResult(**_payload(record)) for record in records]; self._session.add_all(rows); self._session.flush(); return tuple(_metric(row) for row in rows)
    def list_by_conversation(self, conversation_result_id):
        rows = self._session.scalars(select(BenchmarkMetricResult).where(BenchmarkMetricResult.conversation_result_id == conversation_result_id).order_by(BenchmarkMetricResult.metric_key, BenchmarkMetricResult.metric_version, BenchmarkMetricResult.id)).all(); return tuple(_metric(row) for row in rows)
    def list_by_run(self, run_id):
        rows = self._session.scalars(
            select(BenchmarkMetricResult)
            .join(BenchmarkConversationResult)
            .where(BenchmarkConversationResult.benchmark_run_id == run_id)
            .order_by(
                BenchmarkConversationResult.test_case_key,
                BenchmarkMetricResult.metric_key,
                BenchmarkMetricResult.metric_version,
                BenchmarkMetricResult.id,
            )
        ).all()
        return tuple(_metric(row) for row in rows)
    def aggregate_by_metric_key(self, conversation_result_id): return self._aggregate(BenchmarkMetricResult.conversation_result_id == conversation_result_id)
    def aggregate_by_model_run(self, run_id): return self._aggregate(BenchmarkConversationResult.benchmark_run_id == run_id, join=True)
    def _aggregate(self, criterion, join=False):
        stmt = select(BenchmarkMetricResult.metric_key, func.avg(BenchmarkMetricResult.normalized_score)).where(BenchmarkMetricResult.normalized_score.is_not(None))
        if join: stmt = stmt.join(BenchmarkConversationResult)
        rows = self._session.execute(stmt.where(criterion).group_by(BenchmarkMetricResult.metric_key).order_by(BenchmarkMetricResult.metric_key)).all()
        return {key: Decimal(str(value)) for key, value in rows}


class BenchmarkFailureRepository:
    def __init__(self, session): self._session = session
    def insert(self, record): return self.bulk_insert((record,))[0]
    def bulk_insert(self, records):
        rows = [BenchmarkFailureEvent(**_payload(record)) for record in records]; self._session.add_all(rows); self._session.flush(); return tuple(_failure(row) for row in rows)
    def list_by_conversation(self, conversation_result_id):
        rows = self._session.scalars(select(BenchmarkFailureEvent).where(BenchmarkFailureEvent.conversation_result_id == conversation_result_id).order_by(BenchmarkFailureEvent.is_primary.desc(), BenchmarkFailureEvent.created_at, BenchmarkFailureEvent.id)).all(); return tuple(_failure(row) for row in rows)
    def list_by_run(self, run_id):
        rows = self._session.scalars(
            select(BenchmarkFailureEvent)
            .join(BenchmarkConversationResult)
            .where(BenchmarkConversationResult.benchmark_run_id == run_id)
            .order_by(
                BenchmarkConversationResult.test_case_key,
                BenchmarkFailureEvent.is_primary.desc(),
                BenchmarkFailureEvent.created_at,
                BenchmarkFailureEvent.id,
            )
        ).all()
        return tuple(_failure(row) for row in rows)
    def aggregate_by_category(self, run_id): return self._aggregate(run_id, BenchmarkFailureEvent.failure_category)
    def aggregate_by_responsibility_layer(self, run_id): return self._aggregate(run_id, BenchmarkFailureEvent.responsibility_layer)
    def _aggregate(self, run_id, column):
        rows = self._session.execute(select(column, func.count()).join(BenchmarkConversationResult).where(BenchmarkConversationResult.benchmark_run_id == run_id).group_by(column).order_by(column)).all(); return {key: count for key, count in rows}
