"""Trusted entity continuity without provider-visible identity storage."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Optional
from uuid import UUID

from app.conversation_state import (
    ConversationFocus,
    ConversationState,
    EntityReference,
    EntityType,
    RelationshipType,
    StateMetadata,
    StateStatus,
    VerificationSource,
)
from app.conversation_continuity.contracts import (
    ContinuityAuditMetadata,
    ContinuityFailureCategory,
    ContinuityResolutionMethod,
    TrustedContinuityBindingContext,
    TrustedConversationEntityState,
    TrustedEntityReference,
    TrustedEntityStatus,
    TrustedEntityType,
)
from app.tools.context import ExecutionContext
from app.tools.execution_request import ToolExecutionRequest
from app.tools.result import ToolResult, ToolStatus
from app.tools.selection import ToolSelectionRequest


class TrustedContinuityError(RuntimeError):
    """Safe structured continuity failure."""

    def __init__(self, category: ContinuityFailureCategory, public_message: str) -> None:
        self.category = category
        self.public_message = public_message
        super().__init__(public_message)


class TrustedContinuityStore:
    """Thread-safe process-local store shared by configured runtime views."""

    def __init__(self) -> None:
        self._states: dict[UUID, TrustedConversationEntityState] = {}
        self._lock = RLock()

    def load(self, conversation_id: UUID) -> Optional[TrustedConversationEntityState]:
        with self._lock:
            state = self._states.get(conversation_id)
            return None if state is None else state.model_copy(deep=True)

    def save(self, state: TrustedConversationEntityState) -> None:
        with self._lock:
            current = self._states.get(state.conversation_id)
            expected = 0 if current is None else current.revision + 1
            if state.revision != expected:
                raise TrustedContinuityError(
                    ContinuityFailureCategory.PERSISTENCE_FAILURE,
                    "Conversation context could not be saved safely.",
                )
            self._states[state.conversation_id] = state.model_copy(deep=True)

    def delete(self, conversation_id: UUID) -> bool:
        with self._lock:
            return self._states.pop(conversation_id, None) is not None


class TrustedConversationEntityContinuityService:
    """Capture trusted tool identities and resolve later anaphoric references."""

    _ORDER_PATTERN = re.compile(r"\b(?:ORD-\d{5,}|CX-[A-Z0-9]+(?:-[A-Z0-9]+)+)\b", re.I)
    _MASKED_PATTERN = re.compile(r"(?:ORD|CX)-[^\s]*\*+[^\s]*", re.I)
    _ORDINALS = (
        (0, re.compile(r"\b(?:first(?: one)?|number one|awel wa7ed|el awel)\b|(?:الأول|اول واحد|أول واحد)", re.I)),
        (1, re.compile(r"\b(?:second(?: one)?|number two|el tany|eltany)\b|(?:التاني|الثاني|رقم اتنين)", re.I)),
        (2, re.compile(r"\b(?:third(?: one)?|number three|el talet)\b|(?:التالت|الثالث)", re.I)),
    )
    _SELECTED = re.compile(
        r"\b(?:that order|this order|check it|that one|el order da|el order dah)\b|"
        r"(?:الأوردر ده|الطلب ده|ده|شوفه|شيك عليه)", re.I
    )
    _LAST = re.compile(
        r"\b(?:last(?: order| one)?|latest order|akher order|el akher)\b|"
        r"(?:آخر أوردر|اخر اوردر|الأخير|الاخير)", re.I
    )

    def __init__(
        self,
        *,
        store: Optional[TrustedContinuityStore] = None,
        order_tool_names: Iterable[str] = (),
        ttl: timedelta = timedelta(minutes=30),
        max_turn_gap: int = 20,
        clock: Optional[Callable[[], datetime]] = None,
        audit_sink: Optional[Callable[[ContinuityAuditMetadata], None]] = None,
    ) -> None:
        if ttl <= timedelta(0) or max_turn_gap < 1:
            raise ValueError("trusted continuity expiration must be positive")
        self._store = store or TrustedContinuityStore()
        self._order_tools = frozenset(name.strip() for name in order_tool_names)
        if any(not name for name in self._order_tools):
            raise ValueError("order tool names must not be blank")
        self._ttl = ttl
        self._max_turn_gap = max_turn_gap
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._audit_sink = audit_sink or (lambda metadata: None)

    def for_order_tools(self, names: Iterable[str]) -> "TrustedConversationEntityContinuityService":
        return TrustedConversationEntityContinuityService(
            store=self._store,
            order_tool_names=names,
            ttl=self._ttl,
            max_turn_gap=self._max_turn_gap,
            clock=self._clock,
            audit_sink=self._audit_sink,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise TrustedContinuityError(
                ContinuityFailureCategory.PERSISTENCE_FAILURE,
                "Conversation context is temporarily unavailable.",
            )
        return value.astimezone(timezone.utc)

    def prepare_binding(
        self,
        selection: ToolSelectionRequest,
        context: ExecutionContext,
        customer_message: str,
        source_turn: int,
    ) -> TrustedContinuityBindingContext:
        if selection.tool_name not in self._order_tools:
            return self._binding(customer_message, None, consulted=False)
        state = self._validated_state(context, source_turn)
        explicit = self._ORDER_PATTERN.search(customer_message)
        masked = self._MASKED_PATTERN.search(customer_message)
        ordinal = next(
            ((index, pattern) for index, pattern in self._ORDINALS if pattern.search(customer_message)),
            None,
        )
        last_reference = self._LAST.search(customer_message)
        selected_reference = self._SELECTED.search(customer_message)

        if masked is not None and ordinal is None and selected_reference is None:
            self._fail(ContinuityFailureCategory.UNSUPPORTED_REFERENCE)
        if explicit is not None and masked is None:
            return self._binding(
                customer_message,
                self._as_conversation_state(state),
                consulted=state is not None,
                method=ContinuityResolutionMethod.EXPLICIT_REFERENCE,
            )
        if ordinal is not None:
            if state is None:
                self._fail(ContinuityFailureCategory.NO_TRUSTED_ENTITY)
            index = ordinal[0]
            if index >= len(state.candidates):
                self._fail(ContinuityFailureCategory.INVALID_CANDIDATE_INDEX)
            reference = state.candidates[index]
            state = self._select(state, reference, source_turn)
            return self._reused(reference, state, ContinuityResolutionMethod.CANDIDATE_INDEX)
        if last_reference is not None:
            if state is None:
                self._fail(ContinuityFailureCategory.NO_TRUSTED_ENTITY)
            if not state.candidates:
                self._fail(ContinuityFailureCategory.AMBIGUOUS_REFERENCE)
            reference = state.candidates[-1]
            state = self._select(state, reference, source_turn)
            return self._reused(
                reference, state, ContinuityResolutionMethod.CANDIDATE_INDEX
            )
        if selected_reference is not None:
            if state is None:
                self._fail(ContinuityFailureCategory.NO_TRUSTED_ENTITY)
            if state.selected_entity is not None:
                return self._reused(
                    state.selected_entity, state, ContinuityResolutionMethod.SELECTED_ENTITY
                )
            if len(state.candidates) == 1:
                state = self._select(state, state.candidates[0], source_turn)
                return self._reused(
                    state.candidates[0], state, ContinuityResolutionMethod.SELECTED_ENTITY
                )
            self._fail(ContinuityFailureCategory.AMBIGUOUS_REFERENCE)
        return self._binding(
            customer_message,
            self._as_conversation_state(state),
            consulted=state is not None,
        )

    def record_success(
        self,
        request: ToolExecutionRequest,
        result: ToolResult,
        source_turn: int,
    ) -> None:
        if result.status is not ToolStatus.SUCCESS or result.data is None:
            return
        context = request.context
        if context.customer_id is None or context.conversation_id is None:
            return
        payload = result.data.model_dump(mode="python")
        references: list[str] = []
        selected: Optional[str] = None
        direct = payload.get("order_number")
        if isinstance(direct, str) and self._ORDER_PATTERN.fullmatch(direct.strip()):
            selected = direct.strip().upper()
        orders = payload.get("orders")
        if isinstance(orders, (list, tuple)):
            for item in orders:
                raw = item.get("order_number") if isinstance(item, dict) else None
                if isinstance(raw, str) and self._ORDER_PATTERN.fullmatch(raw.strip()):
                    references.append(raw.strip().upper())
        if selected is None and not references:
            return
        now = self._now()
        existing = self._store.load(context.conversation_id)
        if existing is not None and existing.customer_id != context.customer_id:
            self._fail(ContinuityFailureCategory.CUSTOMER_MISMATCH)
        created = now if existing is None else existing.created_at

        def ref(value: str) -> TrustedEntityReference:
            return TrustedEntityReference(
                entity_type=TrustedEntityType.ORDER,
                public_reference=value,
                customer_id=context.customer_id,
                conversation_id=context.conversation_id,
                source_tool=request.tool_name,
                source_turn=source_turn,
                verified_at=now,
            )

        candidates = tuple(ref(value) for value in references)
        selected_entity = ref(selected) if selected is not None else (
            existing.selected_entity if existing is not None else None
        )
        state = TrustedConversationEntityState(
            conversation_id=context.conversation_id,
            customer_id=context.customer_id,
            revision=0 if existing is None else existing.revision + 1,
            selected_entity=selected_entity,
            candidates=candidates if candidates else (existing.candidates if existing else ()),
            created_at=created,
            updated_at=now,
            expires_at=now + self._ttl,
            expires_after_turn=source_turn + self._max_turn_gap,
        )
        self._store.save(state)

    def clear(self, conversation_id: UUID) -> bool:
        return self._store.delete(conversation_id)

    def load(self, conversation_id: UUID) -> Optional[TrustedConversationEntityState]:
        return self._store.load(conversation_id)

    def _validated_state(
        self, context: ExecutionContext, source_turn: int
    ) -> Optional[TrustedConversationEntityState]:
        if context.conversation_id is None or context.customer_id is None:
            return None
        state = self._store.load(context.conversation_id)
        if state is None:
            return None
        if state.conversation_id != context.conversation_id:
            self._fail(ContinuityFailureCategory.CONVERSATION_MISMATCH)
        if state.customer_id != context.customer_id:
            self._fail(ContinuityFailureCategory.CUSTOMER_MISMATCH)
        if state.expires_at <= self._now() or source_turn > state.expires_after_turn:
            self._store.delete(context.conversation_id)
            self._fail(ContinuityFailureCategory.STALE_ENTITY)
        return state

    def _select(
        self,
        state: TrustedConversationEntityState,
        reference: TrustedEntityReference,
        source_turn: int,
    ) -> TrustedConversationEntityState:
        now = self._now()
        updated = state.model_copy(
            update={
                "revision": state.revision + 1,
                "selected_entity": reference,
                "updated_at": now,
                "expires_at": now + self._ttl,
                "expires_after_turn": source_turn + self._max_turn_gap,
            },
            deep=True,
        )
        self._store.save(updated)
        return updated

    def _reused(
        self,
        reference: TrustedEntityReference,
        state: TrustedConversationEntityState,
        method: ContinuityResolutionMethod,
    ) -> TrustedContinuityBindingContext:
        return self._binding(
            reference.public_reference,
            self._as_conversation_state(state),
            consulted=True,
            reused=True,
            reference=reference,
            method=method,
        )

    def _as_conversation_state(
        self, state: Optional[TrustedConversationEntityState]
    ) -> Optional[ConversationState]:
        if state is None:
            return None
        def convert(item: TrustedEntityReference, relationship: RelationshipType) -> EntityReference:
            return EntityReference(
                entity_type=EntityType.ORDER,
                relationship=relationship,
                reference=item.public_reference,
                verification_source=VerificationSource.VERIFIED_TOOL_RESULT,
                verified_at=item.verified_at,
                valid_until=state.expires_at,
                source_tool_call_id=f"continuity-turn-{item.source_turn}",
            )
        selected = (
            convert(state.selected_entity, RelationshipType.SELECTED)
            if state.selected_entity is not None else None
        )
        candidates = tuple(convert(item, RelationshipType.ACTIVE) for item in state.candidates)
        return ConversationState(
            metadata=StateMetadata(
                state_id=state.state_id,
                conversation_id=state.conversation_id,
                revision=state.revision,
                status=StateStatus.ACTIVE,
                created_at=state.created_at,
                updated_at=state.updated_at,
                expires_at=state.expires_at,
            ),
            focus=ConversationFocus(
                primary_entity=selected,
                related_entities=candidates,
                established_at_turn=(state.selected_entity.source_turn if state.selected_entity else None),
            ),
            entities=((selected,) if selected else ()) + candidates,
        )

    def _binding(
        self,
        message: str,
        state: Optional[ConversationState],
        *,
        consulted: bool,
        reused: bool = False,
        reference: Optional[TrustedEntityReference] = None,
        method: ContinuityResolutionMethod = ContinuityResolutionMethod.NONE,
    ) -> TrustedContinuityBindingContext:
        audit = ContinuityAuditMetadata(
            consulted=consulted,
            entity_reused=reused,
            entity_type=(reference.entity_type if reference else None),
            source_tool=(reference.source_tool if reference else None),
            source_turn=(reference.source_turn if reference else None),
            resolution_method=method,
        )
        self._audit_sink(audit)
        return TrustedContinuityBindingContext(
            resolver_message=message,
            conversation_state=state,
            audit=audit,
        )

    def _fail(self, category: ContinuityFailureCategory) -> None:
        messages = {
            ContinuityFailureCategory.NO_TRUSTED_ENTITY: "Please identify the order you mean.",
            ContinuityFailureCategory.AMBIGUOUS_REFERENCE: "I found multiple orders. Please specify which one.",
            ContinuityFailureCategory.STALE_ENTITY: "That order context has expired. Please identify it again.",
            ContinuityFailureCategory.CUSTOMER_MISMATCH: "The conversation context could not be verified.",
            ContinuityFailureCategory.CONVERSATION_MISMATCH: "The conversation context could not be verified.",
            ContinuityFailureCategory.UNSUPPORTED_REFERENCE: "Please provide or select a valid order reference.",
            ContinuityFailureCategory.INVALID_CANDIDATE_INDEX: "That order choice is not available. Please select one of the listed orders.",
            ContinuityFailureCategory.PERSISTENCE_FAILURE: "Conversation context is temporarily unavailable.",
        }
        audit = ContinuityAuditMetadata(
            consulted=True,
            entity_reused=False,
            failure_category=category,
        )
        self._audit_sink(audit)
        raise TrustedContinuityError(category, messages[category])
