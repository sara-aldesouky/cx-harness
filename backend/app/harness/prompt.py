"""Provider-independent prompt contracts and context transformation."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.harness.context import (
    ConversationContext,
    ConversationMessage,
)


class PromptMessage(ConversationMessage):
    """One immutable prompt message using the shared conversation semantics.

    Inheriting the conversation-message contract intentionally keeps roles,
    content normalization, and deterministic metadata identical across the
    context and prompt boundaries without provider-specific fields.
    """


class PromptPackage(BaseModel):
    """Immutable standardized prompt consumed by future provider adapters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system_instructions: str
    messages: tuple[PromptMessage, ...]
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
        cls, value: tuple[PromptMessage, ...]
    ) -> tuple[PromptMessage, ...]:
        """Require at least one prompt message while preserving its order."""

        if not value:
            raise ValueError("prompt package requires at least one message")
        return value

    @field_validator("provider_name", "model_name")
    @classmethod
    def normalize_optional_selection(cls, value: Optional[str]) -> Optional[str]:
        """Normalize optional routing labels and reject blank selections."""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider and model names must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_provider_selection(self) -> PromptPackage:
        """Keep optional provider and model routing information consistent."""

        if (self.provider_name is None) != (self.model_name is None):
            raise ValueError(
                "provider_name and model_name must both be present or both be absent"
            )
        return self


class PromptManager:
    """Transform validated context into a deterministic neutral prompt package.

    This manager performs contract translation only. Provider adapters remain
    responsible for converting the resulting package into their own external
    request formats.
    """

    @staticmethod
    def create(context: ConversationContext) -> PromptPackage:
        """Revalidate and defensively copy context into prompt contracts."""

        if not isinstance(context, ConversationContext):
            raise TypeError("context must be a ConversationContext")

        validated_context = ConversationContext.model_validate(
            context.model_dump(mode="python")
        )
        messages = tuple(
            PromptMessage.model_validate(message.model_dump(mode="python"))
            for message in validated_context.messages
        )
        return PromptPackage(
            system_instructions=validated_context.system_instructions,
            messages=messages,
            provider_name=validated_context.provider_name,
            model_name=validated_context.model_name,
        )
