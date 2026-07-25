"""Pure unit tests for Stage 7.5 prompt contracts and manager."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.harness import (
    ContextBuilder,
    ConversationContext,
    ConversationMessage,
    ConversationRole,
    PromptManager,
    PromptMessage,
    PromptPackage,
)


def make_context() -> ConversationContext:
    return ContextBuilder.build(
        system_instructions="Be concise.",
        messages=[
            {
                "role": "system",
                "content": "Use customer-safe language.",
                "metadata": {"scope": "support"},
            },
            {"role": "user", "content": "Where is my order?"},
            {"role": "assistant", "content": "I will check."},
            {"role": "tool", "content": "Order is in transit."},
        ],
        provider_name="mock",
        model_name="mock-deterministic-v1",
    )


def test_successful_prompt_creation() -> None:
    prompt = PromptManager.create(make_context())

    assert isinstance(prompt, PromptPackage)
    assert prompt.system_instructions == "Be concise."
    assert all(isinstance(message, PromptMessage) for message in prompt.messages)
    assert prompt.provider_name == "mock"
    assert prompt.model_name == "mock-deterministic-v1"


def test_message_order_and_roles_are_preserved() -> None:
    prompt = PromptManager.create(make_context())

    assert tuple(message.role for message in prompt.messages) == (
        ConversationRole.SYSTEM,
        ConversationRole.USER,
        ConversationRole.ASSISTANT,
        ConversationRole.TOOL,
    )
    assert tuple(message.content for message in prompt.messages) == (
        "Use customer-safe language.",
        "Where is my order?",
        "I will check.",
        "Order is in transit.",
    )


def test_prompt_is_a_defensive_copy_and_context_remains_unchanged() -> None:
    context = make_context()
    before = context.model_dump_json()

    prompt = PromptManager.create(context)

    assert context.model_dump_json() == before
    assert prompt.messages[0] is not context.messages[0]
    assert prompt.messages[0].metadata == (("scope", "support"),)


def test_prompt_contracts_are_immutable() -> None:
    prompt = PromptManager.create(make_context())

    with pytest.raises(ValidationError):
        prompt.system_instructions = "changed"
    with pytest.raises(ValidationError):
        prompt.messages[0].content = "changed"


def test_prompt_output_and_serialization_are_deterministic() -> None:
    context = make_context()

    first = PromptManager.create(context)
    second = PromptManager.create(context)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    serialized = json.loads(first.model_dump_json())
    assert serialized["messages"][0]["metadata"] == [["scope", "support"]]


def test_deferred_provider_selection_is_preserved() -> None:
    context = ContextBuilder.build(
        system_instructions="instructions",
        messages=[{"role": "user", "content": "hello"}],
    )

    prompt = PromptManager.create(context)

    assert prompt.provider_name is None
    assert prompt.model_name is None


@pytest.mark.parametrize("invalid_context", [None, object(), "context", {}])
def test_non_context_input_is_rejected(invalid_context: object) -> None:
    with pytest.raises(TypeError, match="ConversationContext"):
        PromptManager.create(invalid_context)  # type: ignore[arg-type]


def test_constructed_malformed_context_is_revalidated() -> None:
    malformed = ConversationContext.model_construct(
        system_instructions="",
        messages=(),
        provider_name=None,
        model_name=None,
    )

    with pytest.raises(ValidationError):
        PromptManager.create(malformed)


@pytest.mark.parametrize(
    "message",
    [
        {"role": "unknown", "content": "hello"},
        {"role": "user", "content": ""},
        {"content": "missing role"},
    ],
)
def test_prompt_message_rejects_malformed_data(message: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        PromptMessage.model_validate(message)


def test_empty_prompt_package_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one message"):
        PromptPackage(system_instructions="instructions", messages=())


@pytest.mark.parametrize(
    ("provider_name", "model_name"),
    [("mock", None), (None, "model"), (" ", "model"), ("mock", " ")],
)
def test_prompt_package_rejects_invalid_provider_selection(
    provider_name: str | None, model_name: str | None
) -> None:
    with pytest.raises(ValidationError):
        PromptPackage(
            system_instructions="instructions",
            messages=(PromptMessage(role="user", content="hello"),),
            provider_name=provider_name,
            model_name=model_name,
        )


def test_prompt_contracts_forbid_provider_specific_fields() -> None:
    with pytest.raises(ValidationError):
        PromptPackage(
            system_instructions="instructions",
            messages=(PromptMessage(role="user", content="hello"),),
            gemini_generation_config={},
        )


def test_prompt_manager_is_stateless_and_runtime_independent() -> None:
    assert vars(PromptManager()) == {}

    prompt = PromptManager.create(make_context())
    assert isinstance(prompt, PromptPackage)
    assert not hasattr(prompt, "http_client")
    assert not hasattr(prompt, "database_session")
