"""Immutable, provider-neutral conversation context contracts."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
    model_validator,
)


class ConversationRole(str, Enum):
    """Provider-independent roles permitted in conversation history."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


MessageMetadata = tuple[tuple[str, str], ...]


class ConversationMessage(BaseModel):
    """One immutable, ordered unit of provider-independent conversation data.

    Metadata is represented as sorted string pairs instead of a dictionary so
    callers cannot mutate it after validation and serialization is stable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: ConversationRole
    content: str
    metadata: MessageMetadata = ()

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        """Normalize surrounding whitespace and reject empty messages."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("message content must not be empty or whitespace")
        return normalized

    @field_validator("metadata", mode="before")
    @classmethod
    def normalize_metadata(cls, value: object) -> object:
        """Accept a mapping or pair sequence and produce deterministic pairs."""

        if value is None:
            return ()
        if isinstance(value, Mapping):
            value = tuple(value.items())
        try:
            pairs = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError("metadata must contain key/value pairs") from exc

        normalized: list[tuple[str, str]] = []
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ValueError("metadata must contain key/value pairs")
            key, item_value = pair
            if not isinstance(key, str) or not isinstance(item_value, str):
                raise ValueError("metadata keys and values must be strings")
            normalized_key = key.strip()
            normalized_value = item_value.strip()
            if not normalized_key or not normalized_value:
                raise ValueError("metadata keys and values must not be blank")
            normalized.append((normalized_key, normalized_value))

        keys = [key for key, _ in normalized]
        if len(keys) != len(set(keys)):
            raise ValueError("metadata keys must be unique")
        return tuple(sorted(normalized))


class ConversationContext(BaseModel):
    """Immutable context shared by future harness and provider components.

    This contract stores already-selected context only. It does not retrieve,
    assemble, truncate, count, persist, or transform conversation content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    system_instructions: str
    messages: tuple[ConversationMessage, ...]
    provider_name: Optional[str] = None
    model_name: Optional[str] = None

    @field_validator("system_instructions")
    @classmethod
    def normalize_system_instructions(cls, value: str) -> str:
        """Normalize and require explicit system instructions."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("system instructions must not be empty or whitespace")
        return normalized

    @field_validator("messages")
    @classmethod
    def validate_messages(
        cls, value: tuple[ConversationMessage, ...]
    ) -> tuple[ConversationMessage, ...]:
        """Require at least one validated message while preserving its order."""

        if not value:
            raise ValueError("conversation context requires at least one message")
        return value

    @field_validator("provider_name", "model_name")
    @classmethod
    def normalize_optional_selection(cls, value: Optional[str]) -> Optional[str]:
        """Normalize optional provider selection labels and reject blanks."""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider and model names must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_provider_selection(self) -> ConversationContext:
        """Require provider and model identifiers to be selected together."""

        if (self.provider_name is None) != (self.model_name is None):
            raise ValueError(
                "provider_name and model_name must both be present or both be absent"
            )
        return self
