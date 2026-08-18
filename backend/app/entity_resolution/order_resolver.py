"""Provider-independent deterministic order entity resolver."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from app.conversation_state import (
    EntityReference,
    EntityType,
    RelationshipType,
    StateStatus,
    VerificationSource,
)
from app.entity_resolution.contracts import (
    EntityMention,
    EntityResolutionRequest,
    EntityResolutionResult,
    ResolutionCandidate,
    ResolvedEntity,
    ResolutionStatus,
)
from app.entity_resolution.mention_extractor import OrderMentionExtractor
from app.entity_resolution.order_repository import (
    OrderResolutionRecord,
    OrderResolutionRepository,
)


_STATE_VERIFICATION_SOURCES = frozenset(
    {
        VerificationSource.VERIFIED_TOOL_RESULT,
        VerificationSource.REPOSITORY_LOOKUP,
    }
)
_SAFE_NOT_FOUND = "I couldn't find that order for your account."
_SAFE_CLARIFICATION = "I found multiple orders. Please specify the order number."
_SAFE_UNAVAILABLE = "Order information is temporarily unavailable."


class OrderEntityResolver:
    """Resolve one customer-owned order without trusting provider-generated IDs."""

    def __init__(
        self,
        repository: OrderResolutionRepository,
        *,
        mention_extractor: Optional[OrderMentionExtractor] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(repository, OrderResolutionRepository):
            raise TypeError("repository must implement OrderResolutionRepository")
        self._repository = repository
        self._mentions = mention_extractor or OrderMentionExtractor()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("resolver clock must return UTC time")
        return value.astimezone(timezone.utc)

    def resolve(self, request: EntityResolutionRequest) -> EntityResolutionResult:
        if not isinstance(request, EntityResolutionRequest):
            raise TypeError("request must be an EntityResolutionRequest")
        now = self._now()
        mentions = self._mentions.extract(request.customer_message)
        revision = (
            request.conversation_state.metadata.revision
            if request.conversation_state is not None
            else None
        )
        state_failure = self._validate_state(request, now, mentions, revision)
        if state_failure is not None:
            return state_failure
        try:
            if len(mentions) > 1:
                records = tuple(
                    record
                    for mention in mentions
                    for record in (
                        self._repository.find_for_customer(
                            request.trusted_customer_id, mention.public_reference
                        ),
                    )
                    if record is not None
                )
                if len(records) > 1:
                    return self._clarification(records, mentions, revision)
                return self._failure(
                    ResolutionStatus.INVALID_REFERENCE,
                    "ambiguous_explicit_reference",
                    _SAFE_NOT_FOUND,
                    mentions,
                    revision,
                )
            if len(mentions) == 1:
                mention = mentions[0]
                record = self._repository.find_for_customer(
                    request.trusted_customer_id, mention.public_reference
                )
                if record is None:
                    return self._failure(
                        ResolutionStatus.NOT_FOUND,
                        "order_not_found",
                        _SAFE_NOT_FOUND,
                        mentions,
                        revision,
                    )
                return self._resolved(
                    record,
                    RelationshipType.SELECTED,
                    VerificationSource.REPOSITORY_LOOKUP,
                    now,
                    mentions,
                    revision,
                    is_correction=mention.is_correction,
                )
            if self._mentions.contains_malformed_reference(request.customer_message):
                return self._failure(
                    ResolutionStatus.INVALID_REFERENCE,
                    "invalid_order_reference",
                    _SAFE_NOT_FOUND,
                    mentions,
                    revision,
                )
            state_reference = self._selected_state_reference(request)
            if state_reference is None:
                state_reference = self._focused_state_reference(request)
            if state_reference is not None:
                if not self._trusted_state_reference(state_reference, now):
                    return self._failure(
                        ResolutionStatus.INVALID_REFERENCE,
                        "unverified_state_reference",
                        _SAFE_NOT_FOUND,
                        mentions,
                        revision,
                    )
                record = self._repository.find_for_customer(
                    request.trusted_customer_id, state_reference.reference
                )
                if record is None:
                    return self._failure(
                        ResolutionStatus.STALE,
                        "stale_order_reference",
                        _SAFE_NOT_FOUND,
                        mentions,
                        revision,
                    )
                return self._resolved(
                    record,
                    state_reference.relationship,
                    VerificationSource.REPOSITORY_LOOKUP,
                    now,
                    mentions,
                    revision,
                )
            if request.requirement.allow_unique_active_order:
                active = self._repository.list_active_for_customer(
                    request.trusted_customer_id
                )
                if len(active) == 1:
                    return self._resolved(
                        active[0],
                        RelationshipType.ACTIVE,
                        VerificationSource.REPOSITORY_LOOKUP,
                        now,
                        mentions,
                        revision,
                    )
                if len(active) > 1:
                    return self._clarification(active, mentions, revision)
            if request.requirement.allow_latest_order:
                latest = self._repository.latest_for_customer(
                    request.trusted_customer_id
                )
                if latest is not None:
                    return self._resolved(
                        latest,
                        RelationshipType.LATEST,
                        VerificationSource.REPOSITORY_LOOKUP,
                        now,
                        mentions,
                        revision,
                    )
            return self._failure(
                ResolutionStatus.NOT_FOUND,
                "order_not_found",
                _SAFE_NOT_FOUND,
                mentions,
                revision,
            )
        except Exception:
            return self._failure(
                ResolutionStatus.STALE,
                "order_resolution_unavailable",
                _SAFE_UNAVAILABLE,
                mentions,
                revision,
            )

    @staticmethod
    def _validate_state(request, now, mentions, revision):
        state = request.conversation_state
        if state is None:
            return None
        if state.metadata.status is StateStatus.EXPIRED or state.metadata.expires_at <= now:
            return OrderEntityResolver._failure(
                ResolutionStatus.EXPIRED,
                "conversation_state_expired",
                "The conversation context has expired. Please identify the order again.",
                mentions,
                revision,
            )
        if state.metadata.status is not StateStatus.ACTIVE:
            return OrderEntityResolver._failure(
                ResolutionStatus.INVALID_REFERENCE,
                "conversation_state_invalid",
                _SAFE_NOT_FOUND,
                mentions,
                revision,
            )
        return None

    @staticmethod
    def _selected_state_reference(request) -> Optional[EntityReference]:
        state = request.conversation_state
        if state is None:
            return None
        return next(
            (
                reference
                for reference in state.entities
                if reference.entity_type is EntityType.ORDER
                and reference.relationship is RelationshipType.SELECTED
            ),
            None,
        )

    @staticmethod
    def _focused_state_reference(request) -> Optional[EntityReference]:
        state = request.conversation_state
        if state is None or state.focus.primary_entity is None:
            return None
        reference = state.focus.primary_entity
        return reference if reference.entity_type is EntityType.ORDER else None

    @staticmethod
    def _trusted_state_reference(reference: EntityReference, now: datetime) -> bool:
        return (
            reference.verification_source in _STATE_VERIFICATION_SOURCES
            and (reference.valid_until is None or reference.valid_until > now)
        )

    @staticmethod
    def _resolved(
        record: OrderResolutionRecord,
        relationship: RelationshipType,
        source: VerificationSource,
        now: datetime,
        mentions: tuple[EntityMention, ...],
        revision: Optional[int],
        *,
        is_correction: bool = False,
    ) -> EntityResolutionResult:
        return EntityResolutionResult(
            status=ResolutionStatus.RESOLVED,
            resolved_entity=ResolvedEntity(
                entity_type=EntityType.ORDER,
                public_reference=record.order_number,
                relationship=relationship,
                verification_source=source,
                verified_at=now,
                is_customer_correction=is_correction,
            ),
            mentions=mentions,
            public_message="Order resolved successfully.",
            state_revision=revision,
        )

    @staticmethod
    def _clarification(records, mentions, revision) -> EntityResolutionResult:
        ordered = sorted(
            records,
            key=lambda item: (item.created_at, item.order_number),
            reverse=True,
        )
        return EntityResolutionResult(
            status=ResolutionStatus.CLARIFICATION_REQUIRED,
            candidates=tuple(
                ResolutionCandidate(
                    entity_type=EntityType.ORDER,
                    public_reference=record.order_number,
                    relationship=RelationshipType.ACTIVE,
                    created_at=record.created_at,
                )
                for record in ordered
            ),
            mentions=mentions,
            error_code="ambiguous_order_reference",
            public_message=_SAFE_CLARIFICATION,
            state_revision=revision,
        )

    @staticmethod
    def _failure(status, code, message, mentions, revision) -> EntityResolutionResult:
        return EntityResolutionResult(
            status=status,
            mentions=mentions,
            error_code=code,
            public_message=message,
            state_revision=revision,
        )
