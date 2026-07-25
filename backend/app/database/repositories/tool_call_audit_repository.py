"""Write boundary dedicated to the ToolExecutor audit lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import ToolCall

if TYPE_CHECKING:
    from app.tools.context import ExecutionContext


class ToolCallAuditRepository:
    """Create and finalize executor-owned ToolCall audit records."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_running(
        self,
        *,
        context: ExecutionContext,
        tool_name: str,
        tool_version: str,
        input_json: dict[str, object],
        input_truncated: bool,
        started_at: datetime,
    ) -> UUID:
        """Persist the audit row before invoking business code."""

        tool_call = ToolCall(
            execution_id=context.execution_id,
            model_run_id=context.model_run_id,
            conversation_id=context.conversation_id,
            customer_id=context.customer_id,
            tool_name=tool_name,
            tool_version=tool_version,
            status="running",
            input_json=input_json,
            input_truncated=input_truncated,
            success=False,
            requested_at=started_at,
            started_at=started_at,
        )
        with self._session_factory.begin() as session:
            session.add(tool_call)
            session.flush()
            tool_call_id = tool_call.id
        return tool_call_id

    def finalize(
        self,
        tool_call_id: UUID,
        *,
        status: str,
        success: bool,
        output_json: Optional[dict[str, object]],
        output_truncated: bool,
        error_code: Optional[str],
        exception_type: Optional[str],
        finished_at: datetime,
        duration_ms: int,
    ) -> None:
        """Update exactly one existing audit row with its terminal outcome."""

        with self._session_factory.begin() as session:
            tool_call = session.get(ToolCall, tool_call_id)
            if tool_call is None:
                raise RuntimeError("ToolCall audit record disappeared during execution")
            tool_call.status = status
            tool_call.success = success
            tool_call.output_json = output_json
            tool_call.output_truncated = output_truncated
            tool_call.error_code = error_code
            tool_call.exception_type = exception_type
            tool_call.finished_at = finished_at
            tool_call.latency_ms = duration_ms

    def delete_expired_before(self, cutoff: datetime) -> int:
        """Explicitly delete only ToolCall records older than ``cutoff``."""

        with self._session_factory.begin() as session:
            result = session.execute(
                delete(ToolCall).where(ToolCall.created_at < cutoff)
            )
            return result.rowcount or 0

    def count_expired_before(self, cutoff: datetime) -> int:
        """Count retention candidates without modifying them."""

        with self._session_factory() as session:
            return session.scalar(
                select(func.count())
                .select_from(ToolCall)
                .where(ToolCall.created_at < cutoff)
            ) or 0

    def count_stale_running(self, cutoff: datetime) -> int:
        """Count stale running records without modifying them."""

        with self._session_factory() as session:
            return session.scalar(
                select(func.count())
                .select_from(ToolCall)
                .where(*self._stale_criteria(cutoff))
            ) or 0

    def recover_stale_running(
        self,
        *,
        cutoff: datetime,
        recovered_at: datetime,
    ) -> int:
        """Mark stale running records as interrupted, once and idempotently."""

        with self._session_factory.begin() as session:
            return self._recover_stale_records(
                session,
                cutoff=cutoff,
                recovered_at=recovered_at,
            )

    def recover_and_delete(
        self,
        *,
        stale_cutoff: datetime,
        retention_cutoff: datetime,
        recovered_at: datetime,
    ) -> tuple[int, int]:
        """Atomically recover stale rows, then delete expired audit rows."""

        with self._session_factory.begin() as session:
            recovered = self._recover_stale_records(
                session,
                cutoff=stale_cutoff,
                recovered_at=recovered_at,
            )
            result = session.execute(
                delete(ToolCall).where(ToolCall.created_at < retention_cutoff)
            )
            return recovered, result.rowcount or 0

    @staticmethod
    def _stale_criteria(cutoff: datetime) -> tuple:
        return (
            ToolCall.status == "running",
            ToolCall.started_at.is_not(None),
            ToolCall.started_at < cutoff,
        )

    @classmethod
    def _recover_stale_records(
        cls,
        session: Session,
        *,
        cutoff: datetime,
        recovered_at: datetime,
    ) -> int:
        records = list(
            session.scalars(select(ToolCall).where(*cls._stale_criteria(cutoff)))
        )
        for record in records:
            record.status = "error"
            record.success = False
            record.finished_at = recovered_at
            record.latency_ms = max(
                0,
                int((recovered_at - record.started_at).total_seconds() * 1000),
            )
            record.error_code = "stale_execution_recovered"
            record.exception_type = "InterruptedExecution"
            record.output_json = None
            record.output_truncated = False
        return len(records)
