"""Pure unit tests for the Stage 7.6 provider prompt-adapter boundary."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.harness import (
    ContextBuilder,
    MockPromptAdapter,
    PromptAdapter,
    PromptAdapterContractError,
    PromptManager,
    PromptPackage,
    ProviderRequest,
    ProviderRequestMessage,
)


def make_prompt(*, selected: bool = True) -> PromptPackage:
    context = ContextBuilder.build(
        system_instructions=" Preserve these instructions. ",
        messages=[
            {"role": "system", "content": "first"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "third"},
            {
                "role": "tool",
                "content": "fourth",
                "metadata": {"source": "mock"},
            },
        ],
        provider_name="mock" if selected else None,
        model_name="mock-deterministic-v1" if selected else None,
    )
    return PromptManager.create(context)


def test_successful_mock_translation() -> None:
    request = MockPromptAdapter().adapt(make_prompt())

    assert isinstance(request, ProviderRequest)
    assert request.provider_name == "mock"
    assert request.model_name == "mock-deterministic-v1"
    assert all(
        isinstance(message, ProviderRequestMessage)
        for message in request.messages
    )


def test_system_instructions_and_message_order_are_preserved() -> None:
    request = MockPromptAdapter().adapt(make_prompt())

    assert request.system_instructions == "Preserve these instructions."
    assert tuple(message.content for message in request.messages) == (
        "first",
        "second",
        "third",
        "fourth",
    )
    assert request.messages[-1].metadata == (("source", "mock"),)


def test_prompt_package_is_not_mutated_or_retained() -> None:
    prompt = make_prompt()
    before = prompt.model_dump_json()

    request = MockPromptAdapter().adapt(prompt)

    assert prompt.model_dump_json() == before
    assert request.messages[0] is not prompt.messages[0]


def test_translation_is_deterministic_and_json_serializable() -> None:
    prompt = make_prompt()
    adapter = MockPromptAdapter()

    first = adapter.adapt(prompt)
    second = adapter.adapt(prompt)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert json.loads(first.model_dump_json())["messages"][3] == {
        "role": "tool",
        "content": "fourth",
        "metadata": [["source", "mock"]],
    }


def test_translated_request_is_immutable() -> None:
    request = MockPromptAdapter().adapt(make_prompt())

    with pytest.raises(ValidationError):
        request.system_instructions = "changed"
    with pytest.raises(ValidationError):
        request.messages[0].content = "changed"


def test_deferred_prompt_selection_uses_adapter_identity() -> None:
    request = MockPromptAdapter().adapt(make_prompt(selected=False))

    assert request.provider_name == "mock"
    assert request.model_name == "mock-deterministic-v1"


@pytest.mark.parametrize("invalid_prompt", [None, object(), "prompt", {}])
def test_non_prompt_input_is_rejected(invalid_prompt: object) -> None:
    with pytest.raises(TypeError, match="PromptPackage"):
        MockPromptAdapter().adapt(invalid_prompt)  # type: ignore[arg-type]


def test_malformed_constructed_prompt_is_revalidated() -> None:
    malformed = PromptPackage.model_construct(
        system_instructions="", messages=(), provider_name=None, model_name=None
    )

    with pytest.raises(ValidationError):
        MockPromptAdapter().adapt(malformed)


@pytest.mark.parametrize(
    ("provider_name", "model_name", "expected"),
    [
        ("another", "mock-deterministic-v1", "provider"),
        ("mock", "another-model", "model"),
    ],
)
def test_incompatible_prompt_selection_is_rejected(
    provider_name: str, model_name: str, expected: str
) -> None:
    prompt = PromptPackage(
        system_instructions="instructions",
        messages=(ProviderRequestMessage(role="user", content="hello"),),
        provider_name=provider_name,
        model_name=model_name,
    )

    with pytest.raises(ValueError, match=expected):
        MockPromptAdapter().adapt(prompt)


def test_incomplete_adapter_cannot_be_instantiated() -> None:
    class IncompleteAdapter(PromptAdapter):
        pass

    with pytest.raises(TypeError):
        IncompleteAdapter()


def test_adapter_returning_wrong_type_is_rejected() -> None:
    class WrongTypeAdapter(MockPromptAdapter):
        def _translate(self, prompt: PromptPackage) -> ProviderRequest:
            return {"invalid": True}  # type: ignore[return-value]

    with pytest.raises(PromptAdapterContractError, match="ProviderRequest"):
        WrongTypeAdapter().adapt(make_prompt())


def test_adapter_returning_invalid_constructed_request_is_rejected() -> None:
    class InvalidRequestAdapter(MockPromptAdapter):
        def _translate(self, prompt: PromptPackage) -> ProviderRequest:
            return ProviderRequest.model_construct(
                provider_name="mock",
                model_name="mock-deterministic-v1",
                system_instructions="",
                messages=(),
            )

    with pytest.raises(PromptAdapterContractError, match="invalid"):
        InvalidRequestAdapter().adapt(make_prompt())


def test_adapter_output_identity_must_match_adapter() -> None:
    class WrongIdentityAdapter(MockPromptAdapter):
        def _translate(self, prompt: PromptPackage) -> ProviderRequest:
            return ProviderRequest(
                provider_name="another",
                model_name=self.model_name,
                system_instructions=prompt.system_instructions,
                messages=tuple(
                    ProviderRequestMessage.model_validate(message.model_dump())
                    for message in prompt.messages
                ),
            )

    with pytest.raises(PromptAdapterContractError, match="provider_name"):
        WrongIdentityAdapter().adapt(make_prompt())


def test_blank_adapter_identity_is_rejected() -> None:
    class BlankIdentityAdapter(MockPromptAdapter):
        @property
        def provider_name(self) -> str:
            return " "

    with pytest.raises(PromptAdapterContractError, match="provider_name"):
        BlankIdentityAdapter().adapt(make_prompt(selected=False))


def test_adapter_is_runtime_independent() -> None:
    adapter = MockPromptAdapter()

    assert vars(adapter) == {}
    request = adapter.adapt(make_prompt())
    assert not hasattr(request, "http_client")
    assert not hasattr(request, "database_session")
