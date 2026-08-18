"""Storage abstractions and deterministic in-memory conversation state storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Optional
from uuid import UUID

from app.conversation_state.contracts import ConversationState, StateStatus


class ConversationStateStoreError(RuntimeError):
    """Base failure raised by conversation-state storage."""


class ConversationStateAlreadyExistsError(ConversationStateStoreError):
    """Raised when initial state already exists for a conversation."""


class ConversationStateConflictError(ConversationStateStoreError):
    """Raised when optimistic-concurrency revision checks fail."""


class ConversationStateExpiredError(ConversationStateStoreError):
    """Raised once when an expired state is observed and removed."""


class ConversationStateStore(ABC):
    """Provider-independent persistence boundary for immutable state snapshots."""

    @abstractmethod
    def load(self, conversation_id: UUID) -> Optional[ConversationState]: ...

    @abstractmethod
    def save(self, state: ConversationState) -> None: ...

    @abstractmethod
    def compare_and_swap(
        self,
        conversation_id: UUID,
        expected_revision: int,
        state: ConversationState,
    ) -> None: ...

    @abstractmethod
    def delete(self, conversation_id: UUID) -> bool: ...

    @abstractmethod
    def expire(self, conversation_id: UUID) -> Optional[ConversationState]: ...


class InMemoryConversationStateStore(ConversationStateStore):
    """Thread-safe test store with TTL and atomic compare-and-swap semantics."""

    def __init__(
        self, *, clock: Optional[Callable[[], datetime]] = None
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._states: dict[UUID, ConversationState] = {}
        self._lock = RLock()

    @staticmethod
    def _copy(state: ConversationState) -> ConversationState:
        return state.model_copy(deep=True)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ConversationStateStoreError("store clock must return UTC time")
        return value.astimezone(timezone.utc)

    def load(self, conversation_id: UUID) -> Optional[ConversationState]:
        with self._lock:
            state = self._states.get(conversation_id)
            if state is None:
                return None
            if state.metadata.status is StateStatus.EXPIRED or (
                state.metadata.expires_at <= self._now()
            ):
                del self._states[conversation_id]
                raise ConversationStateExpiredError("conversation state has expired")
            return self._copy(state)

    def save(self, state: ConversationState) -> None:
        conversation_id = state.metadata.conversation_id
        with self._lock:
            existing = self._states.get(conversation_id)
            if existing is not None:
                if existing.metadata.expires_at <= self._now():
                    del self._states[conversation_id]
                else:
                    raise ConversationStateAlreadyExistsError(
                        "conversation state already exists"
                    )
            if state.metadata.revision != 0:
                raise ConversationStateConflictError(
                    "initial conversation state revision must be zero"
                )
            self._states[conversation_id] = self._copy(state)

    def compare_and_swap(
        self,
        conversation_id: UUID,
        expected_revision: int,
        state: ConversationState,
    ) -> None:
        if state.metadata.conversation_id != conversation_id:
            raise ConversationStateConflictError("conversation identity mismatch")
        if state.metadata.revision != expected_revision + 1:
            raise ConversationStateConflictError("next revision must increment by one")
        with self._lock:
            existing = self._states.get(conversation_id)
            if existing is None:
                raise ConversationStateConflictError("conversation state is missing")
            if existing.metadata.expires_at <= self._now():
                del self._states[conversation_id]
                raise ConversationStateExpiredError("conversation state has expired")
            if existing.metadata.revision != expected_revision:
                raise ConversationStateConflictError("conversation state revision conflict")
            self._states[conversation_id] = self._copy(state)

    def delete(self, conversation_id: UUID) -> bool:
        with self._lock:
            return self._states.pop(conversation_id, None) is not None

    def expire(self, conversation_id: UUID) -> Optional[ConversationState]:
        with self._lock:
            existing = self._states.get(conversation_id)
            if existing is None:
                return None
            now = self._now()
            metadata = existing.metadata.model_copy(
                update={
                    "revision": existing.metadata.revision + 1,
                    "status": StateStatus.EXPIRED,
                    "updated_at": now,
                }
            )
            expired = existing.model_copy(update={"metadata": metadata}, deep=True)
            self._states[conversation_id] = expired
            return self._copy(expired)
