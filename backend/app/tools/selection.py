"""Provider-neutral contracts for selecting, but never executing, tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_serializer,
    field_validator,
)

from app.tools.immutable_json import freeze_json, json_copy
from app.tools.registry import ToolRegistry


JsonObject = Mapping[str, Any]


class ToolSelectionError(ValueError):
    """Base error for failures at the provider-neutral selection boundary."""


class InvalidToolSelectionRequestError(ToolSelectionError):
    """Raised when the resolver does not receive a selection request contract."""


class DisabledToolSelectionError(ToolSelectionError):
    """Raised when a registered tool is intentionally unavailable."""


class InvalidToolArgumentsError(ToolSelectionError):
    """Raised when arguments do not satisfy the selected tool input schema."""


class ToolSelectionRequest(BaseModel):
    """Immutable model-originated request for a declared business capability.

    ``call_id`` is supplied by the caller and acts as the future correlation key
    between selection, execution, result, and model continuation. This contract
    validates its shape but does not generate or globally track identifiers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    call_id: str
    tool_name: str
    tool_version: Optional[str] = None
    arguments: JsonObject

    @field_validator("call_id", "tool_name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("tool_version")
    @classmethod
    def validate_optional_version(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool_version must not be empty")
        return normalized

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, value: JsonObject) -> JsonObject:
        if not value:
            raise ValueError("arguments must not be empty")
        return freeze_json(value)

    @field_serializer("arguments")
    def serialize_arguments(self, value: JsonObject) -> dict[str, Any]:
        return json_copy(value)


class ValidatedToolSelection(BaseModel):
    """Resolved immutable selection with schema-normalized JSON arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    call_id: str
    tool_name: str
    tool_version: str
    arguments: JsonObject

    @field_validator("arguments")
    @classmethod
    def freeze_arguments(cls, value: JsonObject) -> JsonObject:
        return freeze_json(value)

    @field_serializer("arguments")
    def serialize_arguments(self, value: JsonObject) -> dict[str, Any]:
        return json_copy(value)


class ToolSelectionResolver:
    """Resolve and validate a selection without instantiation or execution."""

    def __init__(self, registry: ToolRegistry) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        self._registry = registry

    def resolve(self, request: ToolSelectionRequest) -> ValidatedToolSelection:
        """Resolve a class and validate arguments through its declared schema."""

        if not isinstance(request, ToolSelectionRequest):
            raise InvalidToolSelectionRequestError(
                "selection request must be a ToolSelectionRequest"
            )

        tool_class = self._registry.get(request.tool_name, request.tool_version)
        if not tool_class.metadata.is_enabled:
            raise DisabledToolSelectionError(
                f"tool {tool_class.metadata.name!r} version "
                f"{tool_class.metadata.version!r} is disabled"
            )

        try:
            validated_input = tool_class.input_schema.model_validate(
                json_copy(request.arguments)
            )
        except ValidationError as error:
            raise InvalidToolArgumentsError(
                f"arguments for tool {tool_class.metadata.name!r} are invalid"
            ) from error

        return ValidatedToolSelection(
            call_id=request.call_id,
            tool_name=tool_class.metadata.name,
            tool_version=tool_class.metadata.version,
            arguments=validated_input.model_dump(mode="json"),
        )
