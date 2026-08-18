"""Immutable provider-neutral contracts for Stage 14 model orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.model_orchestration._immutable_json import freeze_json, json_copy


class _OrchestrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)


class ModelMessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelFinishReason(str, Enum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class ModelProviderCapabilities(_OrchestrationModel):
    """Provider-neutral feature discovery without orchestration branching."""

    tool_calling: bool = False
    streaming: bool = False
    structured_output: bool = False
    system_instructions: bool = True
    image_input: bool = False
    multimodal_input: bool = False
    function_calling: bool = False


class ModelMessage(_OrchestrationModel):
    role: ModelMessageRole
    content: str
    tool_call_id: Optional[str] = None

    @field_validator("content", "tool_call_id")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("message values must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_tool_correlation(self) -> "ModelMessage":
        if self.role is ModelMessageRole.TOOL and self.tool_call_id is None:
            raise ValueError("tool messages require tool_call_id")
        if self.role is not ModelMessageRole.TOOL and self.tool_call_id is not None:
            raise ValueError("only tool messages may contain tool_call_id")
        return self


class AvailableModelTool(_OrchestrationModel):
    name: str
    version: str
    description: str
    input_schema: Mapping[str, Any]

    @field_validator("name", "version", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool metadata must not be blank")
        return normalized

    @field_validator("input_schema")
    @classmethod
    def freeze_schema(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not value:
            raise ValueError("input_schema must not be empty")
        return freeze_json(value)

    @field_serializer("input_schema")
    def serialize_schema(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)


class ModelGenerationSettings(_OrchestrationModel):
    temperature: float = 0.0
    max_output_tokens: int = 256
    top_p: Optional[float] = None
    stop_sequences: tuple[str, ...] = ()

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if value < 0 or value > 2:
            raise ValueError("temperature must be between 0 and 2")
        return value

    @field_validator("max_output_tokens")
    @classmethod
    def validate_output_limit(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("max_output_tokens must be positive")
        return value

    @field_validator("top_p")
    @classmethod
    def validate_top_p(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and (value <= 0 or value > 1):
            raise ValueError("top_p must be greater than 0 and at most 1")
        return value

    @field_validator("stop_sequences")
    @classmethod
    def normalize_stops(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("stop sequences must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("stop sequences must be unique")
        return normalized


class ModelExecutionMetadata(_OrchestrationModel):
    request_id: UUID
    correlation_id: UUID
    conversation_id: Optional[UUID] = None
    attributes: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def freeze_attributes(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return freeze_json(value)

    @field_serializer("attributes")
    def serialize_attributes(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)


class ModelOrchestrationRequest(_OrchestrationModel):
    system_instructions: str
    messages: tuple[ModelMessage, ...]
    available_tools: tuple[AvailableModelTool, ...] = ()
    generation: ModelGenerationSettings = ModelGenerationSettings()
    execution: ModelExecutionMetadata

    @field_validator("system_instructions")
    @classmethod
    def normalize_instructions(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("system_instructions must not be blank")
        return normalized

    @field_validator("messages")
    @classmethod
    def require_messages(
        cls, value: tuple[ModelMessage, ...]
    ) -> tuple[ModelMessage, ...]:
        if not value:
            raise ValueError("at least one conversation message is required")
        return value

    @field_validator("available_tools")
    @classmethod
    def require_unique_tools(
        cls, value: tuple[AvailableModelTool, ...]
    ) -> tuple[AvailableModelTool, ...]:
        identities = tuple((tool.name, tool.version) for tool in value)
        if len(identities) != len(set(identities)):
            raise ValueError("available tool identities must be unique")
        return value


class NormalizedToolSelection(_OrchestrationModel):
    call_id: str
    tool_name: str
    tool_version: Optional[str] = None
    arguments: Mapping[str, Any]

    @field_validator("call_id", "tool_name", "tool_version")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool selection values must not be blank")
        return normalized

    @field_validator("arguments")
    @classmethod
    def freeze_arguments(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return freeze_json(value)

    @field_serializer("arguments")
    def serialize_arguments(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)


class ModelResponseMetadata(_OrchestrationModel):
    provider_name: str
    model_identifier: str
    request_id: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    finish_reason: ModelFinishReason

    @field_validator("provider_name", "model_identifier", "request_id")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("response metadata values must not be blank")
        return normalized

    @field_validator("latency_ms", "input_tokens", "output_tokens", "total_tokens")
    @classmethod
    def validate_count(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("response counters must be non-negative integers")
        return value

    @model_validator(mode="after")
    def validate_usage(self) -> "ModelResponseMetadata":
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")
        return self


class ModelOrchestrationResponse(_OrchestrationModel):
    assistant_message: Optional[ModelMessage] = None
    tool_selections: tuple[NormalizedToolSelection, ...] = ()
    metadata: ModelResponseMetadata
    provider_metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("tool_selections")
    @classmethod
    def require_unique_calls(
        cls, value: tuple[NormalizedToolSelection, ...]
    ) -> tuple[NormalizedToolSelection, ...]:
        call_ids = tuple(selection.call_id for selection in value)
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool call IDs must be unique")
        return value

    @field_validator("provider_metadata")
    @classmethod
    def freeze_provider_metadata(
        cls, value: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return freeze_json(value)

    @field_serializer("provider_metadata")
    def serialize_provider_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)

    @model_validator(mode="after")
    def validate_response_shape(self) -> "ModelOrchestrationResponse":
        if self.assistant_message is None and not self.tool_selections:
            raise ValueError("a response requires an assistant message or tool selections")
        if (
            self.assistant_message is not None
            and self.assistant_message.role is not ModelMessageRole.ASSISTANT
        ):
            raise ValueError("assistant_message must use the assistant role")
        if self.metadata.finish_reason is ModelFinishReason.TOOL_CALLS:
            if not self.tool_selections:
                raise ValueError("tool_calls finish reason requires tool selections")
        elif self.tool_selections:
            raise ValueError("tool selections require the tool_calls finish reason")
        return self
