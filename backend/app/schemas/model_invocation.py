"""Public transport-neutral schemas for future model invocation APIs."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.harness.context import ConversationRole


class ModelInvocationHistoryMessage(BaseModel):
    """One ordered public history message with no internal metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: ConversationRole
    content: str

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message content must not be empty or whitespace")
        return normalized


class ModelInvocationRequest(BaseModel):
    """Validated public input for one future model-pipeline invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    current_user_message: str
    conversation_history: tuple[ModelInvocationHistoryMessage, ...] = ()
    system_instructions: Optional[str] = None

    @field_validator("current_user_message")
    @classmethod
    def normalize_current_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("current_user_message must not be empty or whitespace")
        return normalized

    @field_validator("system_instructions")
    @classmethod
    def normalize_optional_instructions(
        cls, value: Optional[str]
    ) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("system_instructions must not be whitespace")
        return normalized


class ModelInvocationResponse(BaseModel):
    """Immutable public result containing no audit or transport internals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str
    provider_name: str
    model_name: str

    @field_validator("content", "provider_name", "model_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty or whitespace")
        return normalized
