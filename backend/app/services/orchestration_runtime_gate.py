"""Thread-safe application admission and graceful-shutdown control."""

from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator
from uuid import UUID

from app.services.orchestration_state import OrchestrationCancellationToken


class OrchestrationShuttingDownError(RuntimeError):
    """Raised when a new request arrives after shutdown admission closes."""


class OrchestrationRuntimeGate:
    """Reject new work and cooperatively cancel tracked active invocations."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._accepting = True
        self._active: dict[UUID, OrchestrationCancellationToken] = {}

    @contextmanager
    def execution(self, trace_id: UUID) -> Iterator[OrchestrationCancellationToken]:
        token = OrchestrationCancellationToken()
        with self._lock:
            if not self._accepting:
                raise OrchestrationShuttingDownError(
                    "orchestration runtime is shutting down"
                )
            self._active[trace_id] = token
        try:
            yield token
        finally:
            with self._lock:
                self._active.pop(trace_id, None)

    def begin_shutdown(self) -> int:
        with self._lock:
            self._accepting = False
            tokens = tuple(self._active.values())
        for token in tokens:
            token.cancel()
        return len(tokens)

    def start(self) -> None:
        with self._lock:
            if self._active:
                raise RuntimeError("cannot restart with active executions")
            self._accepting = True

    @property
    def accepting(self) -> bool:
        with self._lock:
            return self._accepting

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)


orchestration_runtime_gate = OrchestrationRuntimeGate()
