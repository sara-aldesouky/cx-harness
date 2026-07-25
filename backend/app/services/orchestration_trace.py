"""Provider-neutral, immutable observability for one orchestration run."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from time import monotonic
from typing import Callable, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


logger = logging.getLogger(__name__)


class OrchestrationTimelineEventType(str, Enum):
    REQUEST_RECEIVED = "request_received"
    PROVIDER_TURN_STARTED = "provider_turn_started"
    PROVIDER_TURN_FINISHED = "provider_turn_finished"
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_FINISHED = "tool_execution_finished"
    FINAL_RESPONSE = "final_response"
    TERMINATION = "termination"
    CLEANUP = "cleanup"


class ProviderResponseType(str, Enum):
    FINAL_RESPONSE = "final_response"
    TOOL_CALLS = "tool_calls"
    INVALID = "invalid"
    ERROR = "error"


class OrchestrationTimelineEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int
    event_type: OrchestrationTimelineEventType
    occurred_at: datetime
    provider_turn: Optional[int] = None
    tool_call_id: Optional[str] = None
    detail: Optional[str] = None


class ProviderTurnTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_number: int
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    response_type: ProviderResponseType
    tool_calls_requested: int
    success: bool
    error_code: Optional[str] = None
    error_type: Optional[str] = None


class ToolExecutionTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_turn: int
    tool_name: str
    tool_call_id: str
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    success: bool
    business_failure_code: Optional[str] = None
    technical_error_type: Optional[str] = None


class OrchestrationDiagnosticSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_turns: int
    tools_executed: int
    total_provider_time_ms: float
    total_tool_time_ms: float
    overall_latency_ms: float
    termination_reason: str
    error_summary: Optional[str]
    cleanup_completed: bool


class OrchestrationExecutionTrace(BaseModel):
    """Complete immutable trace published after cleanup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: UUID
    conversation_id: Optional[UUID]
    provider_name: str
    model_name: str
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    termination_reason: str
    completed: bool
    provider_turns: tuple[ProviderTurnTrace, ...]
    tool_executions: tuple[ToolExecutionTrace, ...]
    timeline: tuple[OrchestrationTimelineEvent, ...]
    diagnostics: OrchestrationDiagnosticSummary


class OrchestrationTraceStateError(RuntimeError):
    """Raised only when internal trace lifecycle ordering is inconsistent."""


class OrchestrationTraceRecorder:
    """Mutable run-local recorder that emits one immutable final trace."""

    def __init__(
        self,
        *,
        trace_id: UUID,
        conversation_id: Optional[UUID],
        provider_name: str,
        model_name: str,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._trace_id = trace_id
        self._conversation_id = conversation_id
        self._provider_name = provider_name.strip().lower()
        self._model_name = model_name.strip()
        self._utcnow = utcnow
        self._clock = clock
        self._started_at = utcnow()
        self._started_monotonic = clock()
        self._provider_turns: list[ProviderTurnTrace] = []
        self._tool_executions: list[ToolExecutionTrace] = []
        self._timeline: list[OrchestrationTimelineEvent] = []
        self._active_provider: Optional[tuple[int, datetime, float]] = None
        self._active_tool: Optional[tuple[int, str, str, datetime, float]] = None
        self._termination_reason: Optional[str] = None
        self._completed = False
        self._error_summary: Optional[str] = None
        self._cleaned = False
        self._final_trace: Optional[OrchestrationExecutionTrace] = None
        self._event(OrchestrationTimelineEventType.REQUEST_RECEIVED)

    def provider_started(self, turn_number: int) -> None:
        if self._active_provider is not None:
            raise OrchestrationTraceStateError("provider turn is already active")
        now = self._utcnow()
        self._active_provider = (turn_number, now, self._clock())
        self._event(
            OrchestrationTimelineEventType.PROVIDER_TURN_STARTED,
            provider_turn=turn_number,
        )

    def provider_finished(
        self,
        *,
        response_type: ProviderResponseType,
        tool_calls_requested: int = 0,
        success: bool,
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
    ) -> None:
        if self._active_provider is None:
            raise OrchestrationTraceStateError("provider turn is not active")
        turn, started_at, started_monotonic = self._active_provider
        ended_at = self._utcnow()
        duration = self._duration(started_monotonic)
        self._provider_turns.append(
            ProviderTurnTrace(
                turn_number=turn,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration,
                response_type=response_type,
                tool_calls_requested=tool_calls_requested,
                success=success,
                error_code=error_code,
                error_type=error_type,
            )
        )
        self._active_provider = None
        self._event(
            OrchestrationTimelineEventType.PROVIDER_TURN_FINISHED,
            provider_turn=turn,
            detail=response_type.value,
        )

    def tool_started(
        self, *, provider_turn: int, tool_name: str, tool_call_id: str
    ) -> None:
        if self._active_tool is not None:
            raise OrchestrationTraceStateError("tool execution is already active")
        now = self._utcnow()
        self._active_tool = (
            provider_turn,
            tool_name,
            tool_call_id,
            now,
            self._clock(),
        )
        self._event(
            OrchestrationTimelineEventType.TOOL_EXECUTION_STARTED,
            provider_turn=provider_turn,
            tool_call_id=tool_call_id,
            detail=tool_name,
        )

    def tool_finished(
        self,
        *,
        success: bool,
        business_failure_code: Optional[str] = None,
        technical_error_type: Optional[str] = None,
    ) -> None:
        if self._active_tool is None:
            raise OrchestrationTraceStateError("tool execution is not active")
        turn, name, call_id, started_at, started_monotonic = self._active_tool
        ended_at = self._utcnow()
        self._tool_executions.append(
            ToolExecutionTrace(
                provider_turn=turn,
                tool_name=name,
                tool_call_id=call_id,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=self._duration(started_monotonic),
                success=success,
                business_failure_code=business_failure_code,
                technical_error_type=technical_error_type,
            )
        )
        self._active_tool = None
        self._event(
            OrchestrationTimelineEventType.TOOL_EXECUTION_FINISHED,
            provider_turn=turn,
            tool_call_id=call_id,
            detail="success" if success else "failure",
        )

    def final_response(self, provider_turn: int) -> None:
        self._event(
            OrchestrationTimelineEventType.FINAL_RESPONSE,
            provider_turn=provider_turn,
        )

    def terminate(
        self,
        *,
        reason: str,
        completed: bool,
        error_summary: Optional[str],
    ) -> None:
        self._close_active_operations("interrupted")
        self._termination_reason = reason
        self._completed = completed
        self._error_summary = error_summary
        self._event(
            OrchestrationTimelineEventType.TERMINATION,
            detail=reason,
        )

    def cleanup(self) -> None:
        self._close_active_operations("cleanup")
        self._cleaned = True
        self._event(OrchestrationTimelineEventType.CLEANUP)

    def build(self) -> OrchestrationExecutionTrace:
        if not self._cleaned or self._termination_reason is None:
            raise OrchestrationTraceStateError(
                "trace must terminate and clean up before publication"
            )
        if self._final_trace is not None:
            return self._final_trace
        ended_at = self._utcnow()
        duration = self._duration(self._started_monotonic)
        diagnostics = OrchestrationDiagnosticSummary(
            provider_turns=len(self._provider_turns),
            tools_executed=len(self._tool_executions),
            total_provider_time_ms=sum(t.duration_ms for t in self._provider_turns),
            total_tool_time_ms=sum(t.duration_ms for t in self._tool_executions),
            overall_latency_ms=duration,
            termination_reason=self._termination_reason,
            error_summary=self._error_summary,
            cleanup_completed=self._cleaned,
        )
        self._final_trace = OrchestrationExecutionTrace(
            trace_id=self._trace_id,
            conversation_id=self._conversation_id,
            provider_name=self._provider_name,
            model_name=self._model_name,
            started_at=self._started_at,
            ended_at=ended_at,
            duration_ms=duration,
            termination_reason=self._termination_reason,
            completed=self._completed,
            provider_turns=tuple(self._provider_turns),
            tool_executions=tuple(self._tool_executions),
            timeline=tuple(self._timeline),
            diagnostics=diagnostics,
        )
        return self._final_trace

    def _close_active_operations(self, error_type: str) -> None:
        if self._active_provider is not None:
            self.provider_finished(
                response_type=ProviderResponseType.ERROR,
                success=False,
                error_code=error_type,
                error_type=error_type,
            )
        if self._active_tool is not None:
            self.tool_finished(success=False, technical_error_type=error_type)

    def _event(
        self,
        event_type: OrchestrationTimelineEventType,
        *,
        provider_turn: Optional[int] = None,
        tool_call_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        event = OrchestrationTimelineEvent(
            sequence=len(self._timeline) + 1,
            event_type=event_type,
            occurred_at=self._utcnow(),
            provider_turn=provider_turn,
            tool_call_id=tool_call_id,
            detail=detail,
        )
        self._timeline.append(event)
        logger.info(
            "orchestration_event event=%s trace_id=%s conversation_id=%s "
            "provider=%s model=%s provider_turn=%s tool_call_id=%s detail=%s",
            event_type.value,
            self._trace_id,
            self._conversation_id,
            self._provider_name,
            self._model_name,
            provider_turn,
            tool_call_id,
            detail,
        )

    def _duration(self, started: float) -> float:
        return max(0.0, (self._clock() - started) * 1000)


def log_execution_trace(trace: OrchestrationExecutionTrace) -> None:
    """Default non-sensitive sink for one completed trace summary."""

    logger.info(
        "orchestration_trace trace_id=%s conversation_id=%s provider=%s model=%s "
        "provider_turn=%s tool_call_id=%s termination=%s completed=%s "
        "duration_ms=%.3f cleanup=%s",
        trace.trace_id,
        trace.conversation_id,
        trace.provider_name,
        trace.model_name,
        None,
        None,
        trace.termination_reason,
        trace.completed,
        trace.duration_ms,
        trace.diagnostics.cleanup_completed,
    )
