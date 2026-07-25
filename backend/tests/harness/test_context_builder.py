"""Pure unit tests for the Stage 7.4 context builder."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.harness import (
    ContextBuilder,
    ConversationContext,
    ConversationMessage,
    ConversationRole,
)


def test_successful_context_construction() -> None:
    context = ContextBuilder.build(
        system_instructions=" Be helpful. ",
        messages=[
            {"role": "user", "content": " Hello "},
            ConversationMessage(role="assistant", content="Welcome"),
        ],
        provider_name=" mock ",
        model_name=" mock-deterministic-v1 ",
    )

    assert isinstance(context, ConversationContext)
    assert context.system_instructions == "Be helpful."
    assert context.messages[0] == ConversationMessage(
        role=ConversationRole.USER, content="Hello"
    )
    assert context.provider_name == "mock"
    assert context.model_name == "mock-deterministic-v1"


def test_message_order_is_preserved_exactly() -> None:
    inputs = [
        {"role": "system", "content": "one"},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": "three"},
        {"role": "tool", "content": "four"},
    ]

    context = ContextBuilder.build(
        system_instructions="instructions", messages=inputs
    )

    assert [message.content for message in context.messages] == [
        "one",
        "two",
        "three",
        "four",
    ]


def test_provider_selection_can_be_assigned() -> None:
    context = ContextBuilder.build(
        system_instructions="instructions",
        messages=[{"role": "user", "content": "hello"}],
        provider_name="mock",
        model_name="mock-deterministic-v1",
    )

    assert (context.provider_name, context.model_name) == (
        "mock",
        "mock-deterministic-v1",
    )


def test_provider_selection_can_be_deferred() -> None:
    context = ContextBuilder.build(
        system_instructions="instructions",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert context.provider_name is None
    assert context.model_name is None


def test_builder_does_not_retain_or_mutate_caller_data() -> None:
    metadata = {"source": "caller"}
    message = {"role": "user", "content": " original ", "metadata": metadata}
    inputs = [message]

    context = ContextBuilder.build(
        system_instructions="instructions", messages=inputs
    )
    message["content"] = "changed"
    metadata["source"] = "changed"
    inputs.append({"role": "assistant", "content": "new"})

    assert len(context.messages) == 1
    assert context.messages[0].content == "original"
    assert context.messages[0].metadata == (("source", "caller"),)


def test_existing_message_is_defensively_copied() -> None:
    original = ConversationMessage(role="user", content="hello")

    context = ContextBuilder.build(
        system_instructions="instructions", messages=[original]
    )

    assert context.messages[0] == original
    assert context.messages[0] is not original


def test_output_is_deterministic() -> None:
    arguments = {
        "system_instructions": "instructions",
        "messages": [
            {
                "role": "user",
                "content": "hello",
                "metadata": {"z": "last", "a": "first"},
            }
        ],
    }

    first = ContextBuilder.build(**arguments)
    second = ContextBuilder.build(**arguments)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert json.loads(first.model_dump_json())["messages"][0]["metadata"] == [
        ["a", "first"],
        ["z", "last"],
    ]


@pytest.mark.parametrize("instructions", ["", "   "])
def test_invalid_system_instructions_are_rejected(instructions: str) -> None:
    with pytest.raises(ValidationError):
        ContextBuilder.build(
            system_instructions=instructions,
            messages=[{"role": "user", "content": "hello"}],
        )


def test_empty_conversation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one message"):
        ContextBuilder.build(system_instructions="instructions", messages=[])


@pytest.mark.parametrize(
    "message",
    [
        {"role": "unknown", "content": "hello"},
        {"role": "user", "content": ""},
        {"content": "missing role"},
        object(),
    ],
)
def test_malformed_message_is_rejected(message: object) -> None:
    expected_error = TypeError if not isinstance(message, dict) else ValidationError
    with pytest.raises(expected_error):
        ContextBuilder.build(
            system_instructions="instructions", messages=[message]
        )


@pytest.mark.parametrize(
    ("provider_name", "model_name"),
    [("mock", None), (None, "model"), (" ", "model"), ("mock", " ")],
)
def test_invalid_provider_selection_is_rejected(
    provider_name: str | None, model_name: str | None
) -> None:
    with pytest.raises(ValidationError):
        ContextBuilder.build(
            system_instructions="instructions",
            messages=[{"role": "user", "content": "hello"}],
            provider_name=provider_name,
            model_name=model_name,
        )


def test_string_is_not_accepted_as_message_collection() -> None:
    with pytest.raises(TypeError, match="ordered collection"):
        ContextBuilder.build(
            system_instructions="instructions", messages="not messages"
        )


def test_builder_is_stateless_and_runtime_independent() -> None:
    assert vars(ContextBuilder()) == {}

    context = ContextBuilder.build(
        system_instructions="instructions",
        messages=(item for item in [{"role": "user", "content": "hello"}]),
    )
    assert context.messages[0].content == "hello"
