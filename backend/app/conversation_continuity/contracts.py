"""Immutable contracts for trusted, customer-scoped entity continuity."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.conversation_state import ConversationState


TRUSTED_CONTINUITY_SCHEMA_VERSION = "1.0"


class TrustedEntityType(str, Enum):
    ORDER = "order"
    CUSTOMER = "customer"
    PAYMENT = "payment"
    REFUND_REQUEST = "refund_request"


class TrustedEntityStatus(str, Enum):
    VERIFIED = "verified"
    STALE = "stale"
    INVALID = "invalid"


class ContinuityResolutionMethod(str, Enum):
    NONE = "none"
    SELECTED_ENTITY = "selected_entity"
    CANDIDATE_INDEX = "candidate_index"
    EXPLICIT_REFERENCE = "explicit_reference"


class ContinuityFailureCategory(str, Enum):
    NO_TRUSTED_ENTITY = "no_trusted_entity"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"
    STALE_ENTITY = "stale_entity"
    CUSTOMER_MISMATCH = "customer_mismatch"
    CONVERSATION_MISMATCH = "conversation_mismatch"
    UNSUPPORTED_REFERENCE = "unsupported_reference"
    INVALID_CANDIDATE_INDEX = "invalid_candidate_index"
    PERSISTENCE_FAILURE = "persistence_failure"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


class _ContinuityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TrustedEntityReference(_ContinuityModel):
    """Verified identity retained outside public/provider-visible messages."""

    entity_type: TrustedEntityType
    internal_entity_id: Optional[UUID] = None
    public_reference: str
    customer_id: UUID
    conversation_id: UUID
    source_tool: str
    source_turn: int
    verified_at: datetime
    status: TrustedEntityStatus = TrustedEntityStatus.VERIFIED

    @field_validator("public_reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("trusted entity text must not be blank")
        return normalized.upper()

    @field_validator("source_tool")
    @classmethod
    def normalize_source_tool(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("source_tool must not be blank")
        return normalized

    @field_validator("source_turn")
    @classmethod
    def validate_turn(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("source_turn must be positive")
        return value

    @field_validator("verified_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)


class TrustedConversationEntityState(_ContinuityModel):
    """One immutable conversation/customer partition of trusted references."""

    schema_version: str = TRUSTED_CONTINUITY_SCHEMA_VERSION
    state_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    customer_id: UUID
    revision: int = 0
    selected_entity: Optional[TrustedEntityReference] = None
    candidates: tuple[TrustedEntityReference, ...] = ()
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    expires_after_turn: int

    @field_validator("schema_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if value != TRUSTED_CONTINUITY_SCHEMA_VERSION:
            raise ValueError("unsupported trusted continuity schema version")
        return value

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, value: int) -> int:
        if value < 0:
            raise ValueError("revision must be non-negative")
        return value

    @field_validator("expires_after_turn")
    @classmethod
    def validate_expiry_turn(cls, value: int) -> int:
        if value < 1:
            raise ValueError("expires_after_turn must be positive")
        return value

    @field_validator("created_at", "updated_at", "expires_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_partition(self) -> "TrustedConversationEntityState":
        if self.updated_at < self.created_at or self.expires_at <= self.created_at:
            raise ValueError("invalid trusted-state lifecycle")
        references = self.candidates + ((self.selected_entity,) if self.selected_entity else ())
        if any(
            item.customer_id != self.customer_id
            or item.conversation_id != self.conversation_id
            for item in references
        ):
            raise ValueError("trusted entity does not belong to its state partition")
        return self


class ContinuityAuditMetadata(_ContinuityModel):
    """Sanitized metadata; it deliberately contains no business identifiers."""

    consulted: bool
    entity_reused: bool
    entity_type: Optional[TrustedEntityType] = None
    source_tool: Optional[str] = None
    source_turn: Optional[int] = None
    resolution_method: ContinuityResolutionMethod = ContinuityResolutionMethod.NONE
    failure_category: Optional[ContinuityFailureCategory] = None


class TrustedContinuityBindingContext(_ContinuityModel):
    """Trusted resolver input prepared before the frozen binder is invoked."""

    resolver_message: str
    conversation_state: Optional[ConversationState] = None
    audit: ContinuityAuditMetadata

    @field_validator("resolver_message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("resolver_message must not be blank")
        return normalized
