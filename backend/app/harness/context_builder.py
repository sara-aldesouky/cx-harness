"""Stateless assembly of validated provider-neutral conversation context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional, Union

from app.harness.context import ConversationContext, ConversationMessage


MessageInput = Union[ConversationMessage, Mapping[str, object]]


class ContextBuilder:
    """Build immutable context by delegating validation to its contracts.

    The builder performs defensive copying and assembly only. It does not
    retrieve messages, interpret business data, format prompts, count tokens,
    or depend on providers and infrastructure.
    """

    @staticmethod
    def build(
        *,
        system_instructions: str,
        messages: Iterable[MessageInput],
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> ConversationContext:
        """Return a normalized context without retaining caller-owned inputs."""

        if isinstance(messages, (str, bytes)):
            raise TypeError("messages must be an ordered collection of messages")

        copied_messages = tuple(
            ContextBuilder._copy_message(message) for message in messages
        )
        return ConversationContext(
            system_instructions=system_instructions,
            messages=copied_messages,
            provider_name=provider_name,
            model_name=model_name,
        )

    @staticmethod
    def _copy_message(message: MessageInput) -> ConversationMessage:
        """Validate one input and create a context-owned immutable message."""

        if isinstance(message, ConversationMessage):
            payload = message.model_dump(mode="python")
        elif isinstance(message, Mapping):
            payload = dict(message)
        else:
            raise TypeError(
                "each message must be a ConversationMessage or mapping"
            )
        return ConversationMessage.model_validate(payload)
