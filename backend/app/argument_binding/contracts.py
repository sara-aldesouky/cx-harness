"""Immutable provider-neutral contracts for trusted argument binding."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.conversation_state import ConversationState
from app.argument_binding._immutable_json import freeze_json, json_copy
from app.argument_binding.metadata import extension_metadata_copy, freeze_extension_metadata
from app.entity_resolution.contracts import EntityResolutionResult, ResolutionStatus


class BindingStatus(str, Enum):
    BOUND = "bound"
    UNCHANGED = "unchanged"
    CLARIFICATION_REQUIRED = "clarification_required"
    MISSING_REQUIRED_ARGUMENT = "missing_required_argument"
    AMBIGUOUS_ENTITY = "ambiguous_entity"
    UNTRUSTED_ARGUMENT = "untrusted_argument"
    INVALID_TOOL = "invalid_tool"
    POLICY_NOT_FOUND = "policy_not_found"
    RESOLUTION_FAILED = "resolution_failed"


class ArgumentSource(str, Enum):
    EXECUTION_CONTEXT = "execution_context"
    VERIFIED_ENTITY_RESOLUTION = "verified_entity_resolution"
    VERIFIED_CONVERSATION_STATE = "verified_conversation_state"
    REPOSITORY_LOOKUP = "repository_lookup"
    EXPLICIT_CUSTOMER_INPUT = "explicit_customer_input"
    SYSTEM_CONFIGURATION = "system_configuration"
    MODEL_SUGGESTED = "model_suggested"


class ModelValueBehavior(str, Enum):
    ALLOW = "allow"
    DISCARD = "discard"


class UnknownArgumentBehavior(str, Enum):
    REJECT = "reject"
    DISCARD = "discard"


class _BindingModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)


class ProviderToolSelection(_BindingModel):
    """Minimal provider-neutral selection; empty arguments are permitted."""

    tool_name: str
    arguments: Mapping[str, Any] = Field(default_factory=dict)
    call_id: Optional[str] = None
    safe_source_metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("tool_name", "call_id")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("arguments", "safe_source_metadata")
    @classmethod
    def freeze_mapping(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return freeze_json(value)

    @field_serializer("arguments", "safe_source_metadata")
    def serialize_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)


class TrustedExecutionValues(_BindingModel):
    """Core trusted identities plus bounded, non-authoritative metadata."""

    customer_id: UUID
    conversation_id: UUID
    extensions: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("extensions")
    @classmethod
    def freeze_extensions(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return freeze_extension_metadata(value)

    @field_serializer("extensions")
    def serialize_extensions(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return extension_metadata_copy(value)


class ArgumentProvenance(_BindingModel):
    source: ArgumentSource
    protected: bool
    replaced_model_value: bool = False
    injected: bool = False


class BoundArgument(_BindingModel):
    argument_name: str
    value: Any
    provenance: ArgumentProvenance
    included_in_tool_arguments: bool = True

    @field_validator("argument_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("argument_name must not be empty")
        return normalized

    @field_validator("value")
    @classmethod
    def freeze_value(cls, value: Any) -> Any:
        return freeze_json(value)

    @field_serializer("value")
    def serialize_value(self, value: Any) -> Any:
        return json_copy(value)


class BoundToolSelectionRequest(_BindingModel):
    """Executable candidate for later schema validation, never execution here."""

    tool_name: str
    arguments: Mapping[str, Any]
    bound_arguments: tuple[BoundArgument, ...]
    trusted_execution_values: TrustedExecutionValues
    call_id: Optional[str] = None
    safe_source_metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("tool_name", "call_id")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("arguments", "safe_source_metadata")
    @classmethod
    def freeze_mapping(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return freeze_json(value)

    @field_serializer("arguments", "safe_source_metadata")
    def serialize_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)


class BindingFailure(_BindingModel):
    code: str
    public_message: str
    resolution_status: Optional[ResolutionStatus] = None

    @field_validator("code", "public_message")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


class BindingAuditMetadata(_BindingModel):
    """Sanitized counts and categories suitable for a future audit sink."""

    binding_status: BindingStatus
    protected_argument_count: int
    injected_argument_count: int
    replaced_argument_count: int
    provenance_categories: tuple[ArgumentSource, ...] = ()
    resolver_outcome: Optional[ResolutionStatus] = None

    @field_validator(
        "protected_argument_count",
        "injected_argument_count",
        "replaced_argument_count",
    )
    @classmethod
    def validate_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("audit counts must be non-negative")
        return value

    @field_validator("provenance_categories")
    @classmethod
    def normalize_categories(
        cls, values: tuple[ArgumentSource, ...]
    ) -> tuple[ArgumentSource, ...]:
        return tuple(sorted(set(values), key=lambda item: item.value))


class ArgumentBindingRequest(_BindingModel):
    selection: ProviderToolSelection
    trusted_values: TrustedExecutionValues
    current_customer_message: str
    conversation_state: Optional[ConversationState] = None
    allow_unique_active_order: bool = True
    allow_latest_order: bool = False
    correlation_id: Optional[str] = None

    @field_validator("current_customer_message", "correlation_id")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_partition(self) -> ArgumentBindingRequest:
        if (
            self.conversation_state is not None
            and self.conversation_state.metadata.conversation_id
            != self.trusted_values.conversation_id
        ):
            raise ValueError("conversation state partition does not match trusted context")
        return self


class ArgumentBindingResult(_BindingModel):
    status: BindingStatus
    bound_selection: Optional[BoundToolSelectionRequest] = None
    failure: Optional[BindingFailure] = None
    resolution_result: Optional[EntityResolutionResult] = None
    injected_count: int = 0
    replaced_count: int = 0
    audit_metadata: Optional[BindingAuditMetadata] = None

    @model_validator(mode="after")
    def validate_shape(self) -> ArgumentBindingResult:
        successful = self.status in {BindingStatus.BOUND, BindingStatus.UNCHANGED}
        if successful and (self.bound_selection is None or self.failure is not None):
            raise ValueError("successful binding requires only a bound selection")
        if not successful and (self.bound_selection is not None or self.failure is None):
            raise ValueError("failed binding requires only a failure")
        if self.injected_count < 0 or self.replaced_count < 0:
            raise ValueError("binding counts must be non-negative")
        return self
