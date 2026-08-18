"""Production prompt injection and model-facing discovery guidance."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.authentication import TrustedCustomerIdentity
from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.harness.ollama_prompt_adapter import OllamaPromptAdapter
from app.harness.production_prompt import (
    PRODUCTION_SYSTEM_PROMPT,
    PRODUCTION_SYSTEM_PROMPT_VERSION,
    ProductionSystemPromptBuilder,
)
from app.harness.prompt import PromptManager
from app.harness.prompt_adapter import MockPromptAdapter
from app.harness.tool_loop_runtime import DEFAULT_BUSINESS_TOOL_CLASSES
from app.identity_roles import PrincipalRole
from app.providers.base import ModelResponse
from app.services.model_tool_loop_service import ModelToolLoopApplicationService
from app.services.orchestration_runtime_gate import OrchestrationRuntimeGate


class RecordingLoop:
    def __init__(self) -> None:
        self.calls = []

    def run(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return SimpleNamespace(
            final_response=ModelResponse(
                content="تمام، هراجع الطلب.",
                provider_name="ollama",
                model_name="qwen3:8b",
            ),
            provider_name="ollama",
            model_name="qwen3:8b",
        )

    def close(self) -> None:
        pass


def identity() -> TrustedCustomerIdentity:
    now = datetime.now(timezone.utc)
    return TrustedCustomerIdentity(
        customer_id=uuid4(),
        authenticated_at=now,
        expires_at=now + timedelta(hours=1),
        authentication_method="test",
        role=PrincipalRole.CUSTOMER,
    )


def service(loop: RecordingLoop) -> ModelToolLoopApplicationService:
    gate = OrchestrationRuntimeGate()
    gate.start()
    return ModelToolLoopApplicationService(
        loop_factory=lambda: loop,
        runtime_gate=gate,
    )


def test_versioned_prompt_contains_mandatory_tool_first_rules() -> None:
    prompt = ProductionSystemPromptBuilder().build()

    assert PRODUCTION_SYSTEM_PROMPT_VERSION in prompt
    for rule in (
        "business tools are the only source of truth",
        "already authenticated through trusted runtime context",
        "Do not ask for an order number before attempting safe discovery",
        "Never claim an operation succeeded until its tool result confirms success",
        "الغيه",
        "3ayz a8ayar el address",
        "initiate_refund",
        "create_support_ticket",
    ):
        assert rule.casefold() in prompt.casefold()


def test_builder_keeps_core_exactly_once_with_supplemental_guidance() -> None:
    builder = ProductionSystemPromptBuilder()
    built = builder.build(f"{PRODUCTION_SYSTEM_PROMPT}\nBe especially concise.")

    assert built.count(PRODUCTION_SYSTEM_PROMPT) == 1
    assert built.endswith("Be especially concise.")
    assert builder.version == PRODUCTION_SYSTEM_PROMPT_VERSION


@pytest.mark.parametrize(
    "customer_message",
    (
        "فين الأوردر؟",
        "تمام الغيه",
        "el order fein?",
        "law sama7t cancel el order",
    ),
)
def test_application_service_injects_hidden_system_prompt(
    customer_message: str,
) -> None:
    loop = RecordingLoop()
    runtime_service = service(loop)

    runtime_service.invoke(
        conversation_id=uuid4(),
        current_user_message=customer_message,
        conversation_history=(
            ConversationMessage(
                role=ConversationRole.ASSISTANT,
                content="أهلاً، أقدر أساعدك.",
            ),
        ),
        system_instructions="Reply concisely.",
        trusted_identity=identity(),
    )

    context = loop.calls[0]["context"]
    assert context.system_instructions.count(PRODUCTION_SYSTEM_PROMPT) == 1
    assert context.system_instructions.startswith(PRODUCTION_SYSTEM_PROMPT)
    assert [message.role for message in context.messages] == [
        ConversationRole.ASSISTANT,
        ConversationRole.USER,
    ]
    assert context.messages[-1].content == customer_message
    assert all(
        PRODUCTION_SYSTEM_PROMPT not in message.content
        for message in context.messages
    )
    assert runtime_service.prompt_version == PRODUCTION_SYSTEM_PROMPT_VERSION


def test_all_prompt_adapters_preserve_the_same_provider_neutral_core() -> None:
    mock_context = ConversationContext(
        system_instructions=PRODUCTION_SYSTEM_PROMPT,
        messages=(ConversationMessage(role=ConversationRole.USER, content="hello"),),
        provider_name="mock",
        model_name="mock-deterministic-v1",
    )
    ollama_context = mock_context.model_copy(
        update={"provider_name": "ollama", "model_name": "qwen3:8b"}
    )

    mock_request = MockPromptAdapter().adapt(PromptManager.create(mock_context))
    ollama_request = OllamaPromptAdapter().adapt(
        PromptManager.create(ollama_context)
    )

    assert mock_request.system_instructions == PRODUCTION_SYSTEM_PROMPT
    assert ollama_request.system_instructions == PRODUCTION_SYSTEM_PROMPT
    assert ollama_request.ollama_messages[0].role == "system"
    assert ollama_request.ollama_messages[0].content == PRODUCTION_SYSTEM_PROMPT
    assert [message.role for message in ollama_request.ollama_messages] == [
        "system",
        "user",
    ]


def test_registered_tool_descriptions_are_actionable_and_trust_safe() -> None:
    definitions = tuple(tool.definition() for tool in DEFAULT_BUSINESS_TOOL_CLASSES)

    assert len({item["name"] for item in definitions}) == len(definitions)
    for definition in definitions:
        description = definition["description"]
        assert "Egyptian Arabic" in description
        assert "Franco-Arabic" in description
        assert "declared schema arguments" in description
        assert "trusted runtime context" in description
        if definition["requires_order_ownership"]:
            assert "active or recent order first" in description
        if not definition["is_read_only"]:
            assert "Do not claim the operation succeeded" in description
