"""Stage 9.5 production-hardening regression tests."""

from __future__ import annotations

from threading import Event, Thread
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.providers.base import ModelResponse, ModelToolLoopTurnResponse
from app.services.model_tool_loop_service import ModelToolLoopTermination
from app.services.orchestration_boundaries import (
    OrchestrationBoundaryValidator,
    OrchestrationBoundaryViolation,
    OrchestrationRuntimeLimits,
)
from app.services.orchestration_runtime_gate import (
    OrchestrationRuntimeGate,
    OrchestrationShuttingDownError,
)
from app.tools.selection import ToolSelectionRequest
from tests.services.test_orchestration_resilience import build, invoke, tool_turn


def limits(**overrides: int) -> OrchestrationRuntimeLimits:
    values = {
        "max_user_message_chars": 1_000,
        "max_conversation_history": 10,
        "max_provider_messages": 20,
        "max_provider_turns": 4,
        "max_tools_exposed": 10,
        "max_tool_calls_per_turn": 4,
        "max_tool_argument_bytes": 1_000,
        "max_tool_result_bytes": 2_000,
        "max_provider_response_bytes": 4_000,
    }
    values.update(overrides)
    return OrchestrationRuntimeLimits(**values)


def test_context_limits_reject_oversized_input_without_payload_in_error() -> None:
    validator = OrchestrationBoundaryValidator(
        limits(max_user_message_chars=4, max_conversation_history=0)
    )
    context = ConversationContext(
        system_instructions="safe",
        messages=(
            ConversationMessage(role=ConversationRole.USER, content="secret-value"),
        ),
    )

    with pytest.raises(OrchestrationBoundaryViolation) as captured:
        validator.validate_context(context)

    assert captured.value.code == "user_message_too_large"
    assert "secret-value" not in str(captured.value)


@pytest.mark.parametrize(
    ("method", "value", "expected_code"),
    [
        ("validate_provider_message_count", 2, "provider_message_limit_exceeded"),
        (
            "validate_provider_response",
            ModelToolLoopTurnResponse(
                tool_calls=tuple(
                    ToolSelectionRequest(
                        call_id=f"call-{index}",
                        tool_name="ping",
                        tool_version="1.0.0",
                        arguments={"message": "ok"},
                    )
                    for index in range(2)
                )
            ),
            "tool_call_limit_exceeded",
        ),
        (
            "validate_tool_call",
            ToolSelectionRequest(
                call_id="large",
                tool_name="ping",
                tool_version="1.0.0",
                arguments={"message": "too-large"},
            ),
            "tool_arguments_too_large",
        ),
    ],
)
def test_runtime_boundaries_have_deterministic_codes(
    method: str, value: object, expected_code: str
) -> None:
    validator = OrchestrationBoundaryValidator(
        limits(
            max_provider_messages=2,
            max_tool_calls_per_turn=1,
            max_tool_argument_bytes=8,
        )
    )

    with pytest.raises(OrchestrationBoundaryViolation) as captured:
        getattr(validator, method)(value)

    assert captured.value.code == expected_code


def test_equivalent_calls_with_regenerated_ids_execute_only_once() -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        return tool_turn(f"regenerated-{request.turn_number}")

    service, _, audit, _ = build(handler)
    result = invoke(service)

    assert result.termination_reason is ModelToolLoopTermination.INVALID_TOOL_CALL
    assert result.error_code == "repeated_tool_call"
    assert result.tools_executed == 1
    assert len(audit.started) == len(audit.finalized) == 1
    assert result.final_response is not None


def test_repeated_tool_with_different_arguments_remains_legitimate() -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        if request.turn_number <= 2:
            return tool_turn(
                f"call-{request.turn_number}", value=f"value-{request.turn_number}"
            )
        return ModelToolLoopTurnResponse(
            final_response=ModelResponse(
                content="Both distinct checks completed.",
                provider_name="resilience",
                model_name="resilience-model",
            )
        )

    service, _, audit, _ = build(handler)
    result = invoke(service)

    assert result.termination_reason is ModelToolLoopTermination.FINAL_RESPONSE
    assert result.tools_executed == 2
    assert len(audit.started) == 2


def test_runtime_gate_rejects_new_work_and_cancels_active_work() -> None:
    gate = OrchestrationRuntimeGate()
    entered = Event()
    release = Event()
    trace_id = uuid4()
    observed = []

    def active_work() -> None:
        with gate.execution(trace_id) as token:
            observed.append(token)
            entered.set()
            release.wait(timeout=2)

    worker = Thread(target=active_work)
    worker.start()
    assert entered.wait(timeout=2)

    assert gate.begin_shutdown() == 1
    assert observed[0].is_cancelled
    with pytest.raises(OrchestrationShuttingDownError):
        with gate.execution(uuid4()):
            pass

    release.set()
    worker.join(timeout=2)
    assert gate.active_count == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_model_turns", 0),
        ("max_model_turns", 101),
        ("max_tools_exposed", 0),
        ("max_provider_response_bytes", 50_000_001),
        ("ollama_connect_timeout_seconds", 0),
        ("ollama_read_timeout_seconds", -1),
        ("ollama_model_name", "   "),
        ("ollama_base_url", "https://example.com"),
        ("ollama_base_url", "ftp://localhost:11434"),
        ("ollama_base_url", "http://user:secret@localhost:11434"),
    ],
)
def test_unsafe_configuration_fails_fast(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
