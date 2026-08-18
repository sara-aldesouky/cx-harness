"""Immutable provider-neutral contracts for deterministic entity resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.conversation_state import (
    ConversationState,
    EntityType,
    RelationshipType,
    VerificationSource,
)


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    CLARIFICATION_REQUIRED = "clarification_required"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    INVALID_REFERENCE = "invalid_reference"
    EXPIRED = "expired"
    STALE = "stale"


class _ResolutionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EntityMention(_ResolutionModel):
    """Exact public entity reference extracted from the customer message."""

    entity_type: EntityType
    public_reference: str
    span_start: int
    span_end: int
    is_correction: bool = False

    @field_validator("public_reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("public_reference must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_span(self) -> EntityMention:
        if self.span_start < 0 or self.span_end <= self.span_start:
            raise ValueError("message span must be positive and ordered")
        return self


class ResolutionRequirement(_ResolutionModel):
    """Caller-declared order resolution behavior, independent of any provider."""

    entity_type: EntityType = EntityType.ORDER
    allow_unique_active_order: bool = True
    allow_latest_order: bool = False

    @field_validator("entity_type")
    @classmethod
    def require_order(cls, value: EntityType) -> EntityType:
        if value is not EntityType.ORDER:
            raise ValueError("Stage 13.2 supports only order resolution")
        return value


class EntityResolutionRequest(_ResolutionModel):
    """Trusted identity, customer message, and optional read-only state snapshot."""

    trusted_customer_id: UUID
    conversation_id: UUID
    customer_message: str
    requirement: ResolutionRequirement = ResolutionRequirement()
    conversation_state: Optional[ConversationState] = None

    @field_validator("customer_message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("customer_message must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_state_partition(self) -> EntityResolutionRequest:
        if (
            self.conversation_state is not None
            and self.conversation_state.metadata.conversation_id
            != self.conversation_id
        ):
            raise ValueError("conversation state partition does not match request")
        return self


class ResolutionCandidate(_ResolutionModel):
    """Minimal customer-safe candidate; internal database IDs are excluded."""

    entity_type: EntityType
    public_reference: str
    relationship: RelationshipType
    created_at: datetime

    @field_validator("public_reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("public_reference must not be empty")
        return normalized

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a UTC timezone")
        return value.astimezone(timezone.utc)


class ResolvedEntity(_ResolutionModel):
    """Repository-verified public entity identity returned by the resolver."""

    entity_type: EntityType
    public_reference: str
    relationship: RelationshipType
    verification_source: VerificationSource
    verified_at: datetime
    is_customer_correction: bool = False

    @field_validator("public_reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("public_reference must not be empty")
        return normalized

    @field_validator("verified_at")
    @classmethod
    def normalize_verified_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified_at must include a UTC timezone")
        return value.astimezone(timezone.utc)


class EntityResolutionResult(_ResolutionModel):
    """Safe deterministic resolution result for exactly one requested entity."""

    status: ResolutionStatus
    resolved_entity: Optional[ResolvedEntity] = None
    candidates: tuple[ResolutionCandidate, ...] = ()
    mentions: tuple[EntityMention, ...] = ()
    error_code: Optional[str] = None
    public_message: str
    state_revision: Optional[int] = None

    @field_validator("error_code")
    @classmethod
    def normalize_error_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("error_code must not be empty")
        return normalized

    @field_validator("public_message")
    @classmethod
    def normalize_public_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("public_message must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_status_shape(self) -> EntityResolutionResult:
        if self.status is ResolutionStatus.RESOLVED:
            if self.resolved_entity is None or self.candidates or self.error_code:
                raise ValueError("resolved result must contain only resolved_entity")
        elif self.resolved_entity is not None:
            raise ValueError("non-resolved result cannot contain resolved_entity")
        if (
            self.status is ResolutionStatus.CLARIFICATION_REQUIRED
            and len(self.candidates) < 2
        ):
            raise ValueError("clarification requires at least two candidates")
        return self
