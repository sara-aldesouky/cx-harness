"""Run-local state and cooperative cancellation for bounded orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Event
from typing import Optional
from uuid import UUID


class OrchestrationPhase(str, Enum):
    """Mutually exclusive phases for one bounded-loop invocation."""

    READY = "ready"
    PROVIDER_RUNNING = "provider_running"
    TOOL_RUNNING = "tool_running"
    TERMINATED = "terminated"
    CLEANED = "cleaned"


class OrchestrationStateError(RuntimeError):
    """Raised when internal orchestration attempts an invalid transition."""


class OrchestrationCancellationToken:
    """Thread-safe cooperative signal checked at every execution boundary."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        """Request graceful termination at the next safe boundary."""

        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class OrchestrationStateSnapshot:
    """Immutable diagnostic view of one run's internal state."""

    trace_id: UUID
    phase: OrchestrationPhase
    provider_turn: int
    active_call_id: Optional[str]
    claimed_call_ids: tuple[str, ...]
    completed_call_ids: tuple[str, ...]
    termination_reason: Optional[str]


class OrchestrationExecutionState:
    """Validate transitions without sharing mutable state between runs."""

    def __init__(self, trace_id: UUID) -> None:
        if not isinstance(trace_id, UUID):
            raise TypeError("trace_id must be a UUID")
        self._trace_id = trace_id
        self._phase = OrchestrationPhase.READY
        self._provider_turn = 0
        self._active_call_id: Optional[str] = None
        self._claimed_call_ids: list[str] = []
        self._completed_call_ids: list[str] = []
        self._termination_reason: Optional[str] = None

    def begin_provider(self, turn_number: int) -> None:
        self._require_phase(OrchestrationPhase.READY)
        if turn_number != self._provider_turn + 1:
            raise OrchestrationStateError("provider turns must be sequential")
        self._provider_turn = turn_number
        self._phase = OrchestrationPhase.PROVIDER_RUNNING

    def finish_provider(self) -> None:
        self._require_phase(OrchestrationPhase.PROVIDER_RUNNING)
        self._phase = OrchestrationPhase.READY

    def begin_tool(self, call_id: str) -> None:
        self._require_phase(OrchestrationPhase.READY)
        normalized = call_id.strip()
        if not normalized:
            raise OrchestrationStateError("call_id must not be blank")
        if normalized in self._claimed_call_ids:
            raise OrchestrationStateError("tool call has already been claimed")
        self._claimed_call_ids.append(normalized)
        self._active_call_id = normalized
        self._phase = OrchestrationPhase.TOOL_RUNNING

    def finish_tool(self) -> None:
        self._require_phase(OrchestrationPhase.TOOL_RUNNING)
        if self._active_call_id is None:
            raise OrchestrationStateError("active tool call is missing")
        self._completed_call_ids.append(self._active_call_id)
        self._active_call_id = None
        self._phase = OrchestrationPhase.READY

    def terminate(self, reason: str) -> None:
        if self._phase is OrchestrationPhase.CLEANED:
            raise OrchestrationStateError("cleaned state cannot terminate again")
        normalized = reason.strip()
        if not normalized:
            raise OrchestrationStateError("termination reason must not be blank")
        self._termination_reason = normalized
        self._active_call_id = None
        self._phase = OrchestrationPhase.TERMINATED

    def cleanup(self) -> None:
        """Discard temporary active state idempotently after every exit path."""

        self._active_call_id = None
        self._phase = OrchestrationPhase.CLEANED

    @property
    def has_active_tool(self) -> bool:
        return self._phase is OrchestrationPhase.TOOL_RUNNING

    @property
    def has_active_provider(self) -> bool:
        return self._phase is OrchestrationPhase.PROVIDER_RUNNING

    def has_claimed(self, call_id: str) -> bool:
        return call_id in self._claimed_call_ids

    def snapshot(self) -> OrchestrationStateSnapshot:
        return OrchestrationStateSnapshot(
            trace_id=self._trace_id,
            phase=self._phase,
            provider_turn=self._provider_turn,
            active_call_id=self._active_call_id,
            claimed_call_ids=tuple(self._claimed_call_ids),
            completed_call_ids=tuple(self._completed_call_ids),
            termination_reason=self._termination_reason,
        )

    def _require_phase(self, expected: OrchestrationPhase) -> None:
        if self._phase is not expected:
            raise OrchestrationStateError(
                f"expected phase {expected.value!r}, found {self._phase.value!r}"
            )
