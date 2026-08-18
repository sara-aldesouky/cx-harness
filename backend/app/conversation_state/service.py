"""Lifecycle service for provider-independent conversation state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import UUID, uuid4

from app.conversation_state.contracts import (
    ConversationState,
    StateMetadata,
    StateStatus,
)
from app.conversation_state.store import ConversationStateStore


class ConversationStateServiceError(ValueError):
    """Raised when lifecycle configuration or input is invalid."""


class ConversationStateService:
    """Create and revise state without knowledge of runtime or business layers."""

    def __init__(
        self,
        store: ConversationStateStore,
        *,
        ttl: timedelta = timedelta(minutes=30),
        clock: Optional[Callable[[], datetime]] = None,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if not isinstance(store, ConversationStateStore):
            raise TypeError("store must implement ConversationStateStore")
        if ttl <= timedelta(0):
            raise ConversationStateServiceError("ttl must be positive")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")
        self._store = store
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ConversationStateServiceError("service clock must return UTC time")
        return value.astimezone(timezone.utc)

    def create(self, conversation_id: UUID) -> ConversationState:
        now = self._now()
        state = ConversationState(
            metadata=StateMetadata(
                state_id=self._id_factory(),
                conversation_id=conversation_id,
                revision=0,
                status=StateStatus.ACTIVE,
                created_at=now,
                updated_at=now,
                expires_at=now + self._ttl,
            )
        )
        self._store.save(state)
        return state.model_copy(deep=True)

    def load(self, conversation_id: UUID) -> Optional[ConversationState]:
        return self._store.load(conversation_id)

    def save(self, state: ConversationState) -> ConversationState:
        now = self._now()
        metadata = state.metadata.model_copy(
            update={
                "revision": state.metadata.revision + 1,
                "updated_at": now,
                "expires_at": now + self._ttl,
            }
        )
        updated = state.model_copy(update={"metadata": metadata}, deep=True)
        self._store.compare_and_swap(
            state.metadata.conversation_id,
            state.metadata.revision,
            updated,
        )
        return updated.model_copy(deep=True)

    def delete(self, conversation_id: UUID) -> bool:
        return self._store.delete(conversation_id)

    def expire(self, conversation_id: UUID) -> Optional[ConversationState]:
        return self._store.expire(conversation_id)
