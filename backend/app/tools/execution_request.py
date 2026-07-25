"""Trusted, provider-neutral command boundary for future tool execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from app.tools.context import ExecutionContext
from app.tools.immutable_json import freeze_json, json_copy
from app.tools.selection import ValidatedToolSelection


class ToolExecutionRequestError(ValueError):
    """Base error for safe execution-request construction failures."""


class InvalidExecutionContextError(ToolExecutionRequestError):
    """Raised when trusted application context is absent or malformed."""


class InvalidExecutionRequestInputError(ToolExecutionRequestError):
    """Raised when construction does not start from a validated selection."""


class ToolExecutionRequest(BaseModel):
    """Deeply immutable execution-ready command with trusted context.

    Application code should construct this contract through
    ``ToolExecutionRequestFactory``. It deliberately contains no raw provider
    response and no registry, schema, repository, or executor reference.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    call_id: str
    tool_name: str
    tool_version: str
    arguments: Mapping[str, Any]
    context: ExecutionContext

    @field_validator("call_id", "tool_name", "tool_version")
    @classmethod
    def validate_required_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("arguments")
    @classmethod
    def freeze_arguments(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not value:
            raise ValueError("arguments must not be empty")
        return freeze_json(value)

    @field_serializer("arguments")
    def serialize_arguments(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)


class ToolExecutionRequestFactory:
    """Combine schema-validated selection with trusted application context."""

    def create(
        self,
        selection: ValidatedToolSelection,
        context: ExecutionContext,
    ) -> ToolExecutionRequest:
        """Build a defensive command without lookup, revalidation, or execution."""

        if not isinstance(selection, ValidatedToolSelection):
            raise InvalidExecutionRequestInputError(
                "selection must be a ValidatedToolSelection"
            )
        if not isinstance(context, ExecutionContext):
            raise InvalidExecutionContextError(
                "context must be a trusted ExecutionContext"
            )

        context_copy = ExecutionContext.model_validate(context.model_dump())
        return ToolExecutionRequest(
            call_id=selection.call_id,
            tool_name=selection.tool_name,
            tool_version=selection.tool_version,
            arguments=json_copy(selection.arguments),
            context=context_copy,
        )
