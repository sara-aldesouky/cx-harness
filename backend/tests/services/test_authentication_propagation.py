"""Authentication propagation at the bounded-loop application boundary."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.authentication import TrustedCustomerIdentity
from app.role_policy import PrincipalRole
from app.providers.base import ModelResponse
from app.services.model_pipeline_service import ModelPipelineServiceInputError
from app.services.model_tool_loop_service import ModelToolLoopApplicationService
from app.services.orchestration_runtime_gate import OrchestrationRuntimeGate


class CapturingLoop:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            final_response=ModelResponse(
                content="grounded",
                provider_name="ollama",
                model_name="qwen3:8b",
            ),
            provider_name="ollama",
            model_name="qwen3:8b",
        )

    def close(self) -> None:
        self.closed = True


def identity(customer_id=None, role=PrincipalRole.CUSTOMER) -> TrustedCustomerIdentity:
    now = datetime.now(timezone.utc)
    return TrustedCustomerIdentity(
        customer_id=customer_id or uuid4(),
        authenticated_at=now,
        expires_at=now + timedelta(hours=1),
        authentication_method="test",
        role=role,
    )


def service_with(loop: CapturingLoop) -> ModelToolLoopApplicationService:
    gate = OrchestrationRuntimeGate()
    gate.start()
    return ModelToolLoopApplicationService(
        loop_factory=lambda: loop,
        runtime_gate=gate,
    )


def test_trusted_identity_populates_execution_context_without_mutation() -> None:
    loop = CapturingLoop()
    trusted = identity()

    result = service_with(loop).invoke(
        conversation_id=uuid4(),
        current_user_message="Where is my order?",
        system_instructions="Use registered tools.",
        trusted_identity=trusted,
    )

    assert result.content == "grounded"
    assert len(loop.calls) == 1
    context = loop.calls[0]["execution_context"]
    assert context.customer_id == trusted.customer_id
    assert context.principal_role == PrincipalRole.CUSTOMER.value
    assert loop.closed is True


def test_trusted_role_is_propagated_without_model_input() -> None:
    loop = CapturingLoop()
    trusted = identity(role=PrincipalRole.CUSTOMER_SUPPORT_AGENT)
    service = service_with(loop)

    service.invoke(
        conversation_id=uuid4(),
        current_user_message="Show the customer order.",
        system_instructions="Be concise.",
        trusted_identity=trusted,
    )

    context = loop.calls[0]["execution_context"]
    assert context.principal_role == PrincipalRole.CUSTOMER_SUPPORT_AGENT.value
    assert loop.closed is True


def test_missing_trusted_identity_prevents_loop_construction() -> None:
    constructed = []
    gate = OrchestrationRuntimeGate()
    gate.start()
    service = ModelToolLoopApplicationService(
        loop_factory=lambda: constructed.append(True),  # type: ignore[arg-type]
        runtime_gate=gate,
    )

    with pytest.raises(ModelPipelineServiceInputError, match="authenticated"):
        service.invoke(
            conversation_id=uuid4(),
            current_user_message="Where is my order?",
            system_instructions="Use registered tools.",
            trusted_identity=None,  # type: ignore[arg-type]
        )

    assert constructed == []
