"""Provider-independent contracts for trusted, short-lived conversation state."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


CURRENT_CONVERSATION_STATE_SCHEMA_VERSION = "1.0"


class EntityType(str, Enum):
    ORDER = "order"
    ORDER_ITEM = "order_item"
    DELIVERY = "delivery"
    REFUND = "refund"
    SUPPORT_TICKET = "support_ticket"
    ADDRESS = "address"


class RelationshipType(str, Enum):
    CURRENT = "current"
    SELECTED = "selected"
    ACTIVE = "active"
    LATEST = "latest"
    PREVIOUS = "previous"
    PENDING = "pending"


class VerificationSource(str, Enum):
    EXECUTION_CONTEXT = "execution_context"
    VERIFIED_TOOL_RESULT = "verified_tool_result"
    REPOSITORY_LOOKUP = "repository_lookup"
    EXPLICIT_CUSTOMER_INPUT = "explicit_customer_input"


class StateStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    INVALID = "invalid"
    ARCHIVED = "archived"


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC timezone")
    return value.astimezone(timezone.utc)


class _StateModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EntityReference(_StateModel):
    """Minimal verified reference to a business entity, never an ORM object."""

    entity_type: EntityType
    relationship: RelationshipType
    reference: str
    verification_source: VerificationSource
    verified_at: datetime
    valid_until: Optional[datetime] = None
    source_tool_call_id: Optional[str] = None

    @field_validator("reference", "source_tool_call_id")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("verified_at", "valid_until")
    @classmethod
    def normalize_timestamp(cls, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _utc_datetime(value)

    @model_validator(mode="after")
    def validate_validity_window(self) -> EntityReference:
        if self.valid_until is not None and self.valid_until <= self.verified_at:
            raise ValueError("valid_until must be later than verified_at")
        return self


class ConversationFocus(_StateModel):
    """Current deterministic entity focus established from trusted evidence."""

    primary_entity: Optional[EntityReference] = None
    related_entities: tuple[EntityReference, ...] = ()
    established_at_turn: Optional[int] = None

    @field_validator("established_at_turn")
    @classmethod
    def validate_turn(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 1:
            raise ValueError("established_at_turn must be positive")
        return value

    @model_validator(mode="after")
    def validate_established_focus(self) -> ConversationFocus:
        if self.primary_entity is None and self.established_at_turn is not None:
            raise ValueError("a focus turn requires a primary entity")
        return self


class PendingOperation(_StateModel):
    """Summary of an incomplete operation; it contains no execution behavior."""

    operation_name: str
    operation_version: str
    target_entity: Optional[EntityReference] = None
    collected_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    initiated_at: datetime
    expires_at: datetime

    @field_validator("operation_name", "operation_version")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("collected_fields", "missing_fields")
    @classmethod
    def normalize_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("field names must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("field names must not contain duplicates")
        return normalized

    @field_validator("initiated_at", "expires_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @model_validator(mode="after")
    def validate_operation_window(self) -> PendingOperation:
        if self.expires_at <= self.initiated_at:
            raise ValueError("expires_at must be later than initiated_at")
        if set(self.collected_fields) & set(self.missing_fields):
            raise ValueError("a field cannot be both collected and missing")
        return self


class LastVerifiedToolOutcome(_StateModel):
    """Customer-safe summary of the last verified tool outcome."""

    tool_name: str
    tool_version: str
    call_id: str
    succeeded: bool
    outcome_code: Optional[str] = None
    verified_at: datetime
    entity_references: tuple[EntityReference, ...] = ()

    @field_validator("tool_name", "tool_version", "call_id", "outcome_code")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("verified_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return _utc_datetime(value)


class StateMetadata(_StateModel):
    """Lifecycle metadata used for revision-safe storage and expiration."""

    state_id: UUID
    conversation_id: UUID
    revision: int
    status: StateStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, value: int) -> int:
        if value < 0:
            raise ValueError("revision must be non-negative")
        return value

    @field_validator("created_at", "updated_at", "expires_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @model_validator(mode="after")
    def validate_lifecycle_timestamps(self) -> StateMetadata:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return self


class ConversationState(_StateModel):
    """Immutable snapshot of trusted conversation state.

    Stage 13.1 stores references and lifecycle summaries only. It deliberately
    contains no resolver, tool, provider, repository, security, or ORM object.
    """

    schema_version: Literal[CURRENT_CONVERSATION_STATE_SCHEMA_VERSION] = (
        CURRENT_CONVERSATION_STATE_SCHEMA_VERSION
    )
    metadata: StateMetadata
    focus: ConversationFocus = ConversationFocus()
    entities: tuple[EntityReference, ...] = ()
    pending_operation: Optional[PendingOperation] = None
    last_verified_tool_outcome: Optional[LastVerifiedToolOutcome] = None

    def to_json(self) -> str:
        """Return deterministic compact JSON using the project Pydantic format."""

        return self.model_dump_json()

    @classmethod
    def from_json(cls, value: str | bytes) -> ConversationState:
        """Deserialize and fail closed for malformed or unsupported versions."""

        return cls.model_validate_json(value)
