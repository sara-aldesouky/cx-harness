"""Provider boundary for translating tool-call intent into neutral contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from app.tools.selection import ToolSelectionRequest


ToolSelections = tuple[ToolSelectionRequest, ...]


class ProviderToolCallAdapterError(ValueError):
    """Base error for provider tool-call translation failures."""


class MalformedProviderToolCallError(ProviderToolCallAdapterError):
    """Raised when a provider response does not match its adapter contract."""


class DuplicateProviderCallIdError(ProviderToolCallAdapterError):
    """Raised when one response contains the same normalized call ID twice."""


class ProviderToolCallAdapter(ABC):
    """Translate one supported provider representation into neutral selections.

    Implementations own provider-format parsing only. They must not resolve a
    registry entry, validate business-tool arguments, instantiate a tool, or
    execute a capability.
    """

    @abstractmethod
    def translate(self, provider_output: object) -> ToolSelections:
        """Return selections in the exact order declared by the provider."""

        raise NotImplementedError


class _MockToolCall(BaseModel):
    """Private parser for the deterministic mock provider representation."""

    model_config = ConfigDict(extra="forbid")

    call_id: StrictStr = Field(alias="id")
    name: StrictStr
    version: Optional[StrictStr] = None
    arguments: dict[str, Any]


class _MockProviderOutput(BaseModel):
    """Private top-level parser; this shape is not a universal provider format."""

    model_config = ConfigDict(extra="forbid")

    tool_calls: tuple[_MockToolCall, ...] = ()


class MockProviderToolCallAdapter(ProviderToolCallAdapter):
    """Deterministically translate the documented mock provider structure."""

    def translate(self, provider_output: object) -> ToolSelections:
        """Parse mock calls without consulting discovery or execution services."""

        try:
            parsed = _MockProviderOutput.model_validate(provider_output)
            selections = tuple(
                ToolSelectionRequest(
                    call_id=call.call_id,
                    tool_name=call.name,
                    tool_version=call.version,
                    arguments=call.arguments,
                )
                for call in parsed.tool_calls
            )
        except ValidationError as error:
            raise MalformedProviderToolCallError(
                "mock provider tool-call payload is malformed"
            ) from error

        call_ids = tuple(selection.call_id for selection in selections)
        if len(set(call_ids)) != len(call_ids):
            raise DuplicateProviderCallIdError(
                "mock provider response contains duplicate call IDs"
            )
        return selections
