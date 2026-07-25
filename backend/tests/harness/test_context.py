"""Pure unit tests for Stage 7.3 conversation context contracts."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.harness import (
    ConversationContext,
    ConversationMessage,
    ConversationRole,
)


def make_messages() -> tuple[ConversationMessage, ...]:
    return (
        ConversationMessage(role=ConversationRole.USER, content="Hello"),
        ConversationMessage(role="assistant", content="How can I help?"),
    )


def test_valid_conversation_context_creation() -> None:
    context = ConversationContext(
        system_instructions=" Be helpful. ",
        messages=make_messages(),
        provider_name=" mock ",
        model_name=" mock-deterministic-v1 ",
    )

    assert context.system_instructions == "Be helpful."
    assert context.provider_name == "mock"
    assert context.model_name == "mock-deterministic-v1"


@pytest.mark.parametrize("role", list(ConversationRole))
def test_every_supported_message_role_is_valid(role: ConversationRole) -> None:
    message = ConversationMessage(role=role, content="content")

    assert message.role is role


def test_unknown_message_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ConversationMessage(role="developer", content="content")


@pytest.mark.parametrize("content", ["", "   "])
def test_empty_message_content_is_rejected(content: str) -> None:
    with pytest.raises(ValidationError):
        ConversationMessage(role="user", content=content)


def test_message_content_and_metadata_are_normalized() -> None:
    message = ConversationMessage(
        role="tool",
        content="  result  ",
        metadata={" source ": " repository ", "call": "status"},
    )

    assert message.content == "result"
    assert message.metadata == (
        ("call", "status"),
        ("source", "repository"),
    )


@pytest.mark.parametrize(
    "metadata",
    [
        (("", "value"),),
        (("key", " "),),
        (("key", "one"), ("key", "two")),
        (("key", 1),),
        ("not-a-pair",),
    ],
)
def test_invalid_metadata_is_rejected(metadata: object) -> None:
    with pytest.raises(ValidationError):
        ConversationMessage(role="user", content="hello", metadata=metadata)


def test_message_order_is_preserved() -> None:
    messages = (
        ConversationMessage(role="system", content="first"),
        ConversationMessage(role="user", content="second"),
        ConversationMessage(role="assistant", content="third"),
        ConversationMessage(role="tool", content="fourth"),
    )

    context = ConversationContext(
        system_instructions="instructions", messages=messages
    )

    assert context.messages == messages
    assert tuple(message.content for message in context.messages) == (
        "first",
        "second",
        "third",
        "fourth",
    )


def test_context_and_nested_messages_are_immutable() -> None:
    context = ConversationContext(
        system_instructions="instructions", messages=make_messages()
    )

    with pytest.raises(ValidationError):
        context.system_instructions = "changed"
    with pytest.raises(ValidationError):
        context.messages[0].content = "changed"


def test_context_serializes_to_json_deterministically() -> None:
    context = ConversationContext(
        system_instructions="instructions",
        messages=(
            ConversationMessage(
                role="user",
                content="hello",
                metadata={"z": "last", "a": "first"},
            ),
        ),
        provider_name="mock",
        model_name="mock-deterministic-v1",
    )

    first = context.model_dump_json()
    second = context.model_dump_json()

    assert first == second
    assert json.loads(first)["messages"][0] == {
        "role": "user",
        "content": "hello",
        "metadata": [["a", "first"], ["z", "last"]],
    }


@pytest.mark.parametrize("instructions", ["", "   "])
def test_empty_system_instructions_are_rejected(instructions: str) -> None:
    with pytest.raises(ValidationError):
        ConversationContext(
            system_instructions=instructions, messages=make_messages()
        )


def test_empty_conversation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one message"):
        ConversationContext(system_instructions="instructions", messages=())


@pytest.mark.parametrize(
    ("provider_name", "model_name"),
    [("mock", None), (None, "model"), (" ", "model"), ("mock", " ")],
)
def test_invalid_provider_selection_is_rejected(
    provider_name: str | None, model_name: str | None
) -> None:
    with pytest.raises(ValidationError):
        ConversationContext(
            system_instructions="instructions",
            messages=make_messages(),
            provider_name=provider_name,
            model_name=model_name,
        )


def test_provider_selection_may_be_deferred() -> None:
    context = ConversationContext(
        system_instructions="instructions", messages=make_messages()
    )

    assert context.provider_name is None
    assert context.model_name is None


def test_contracts_reject_undeclared_fields() -> None:
    with pytest.raises(ValidationError):
        ConversationMessage(
            role="user",
            content="hello",
            provider_specific_value="not allowed",
        )
