"""Stage 9.3 resilience tests for the existing bounded orchestration loop."""

from __future__ import annotations

from concurrent.futures import CancelledError, ThreadPoolExecutor
from threading import Lock
from typing import Callable
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.providers.base import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelToolLoopTurnResponse,
    ProviderCapabilities,
)
from app.providers.registry import ProviderRegistry
from app.services.model_tool_loop_service import (
    BoundedModelToolLoopService,
    ModelToolLoopTermination,
)
from app.services.orchestration_state import (
    OrchestrationCancellationToken,
    OrchestrationExecutionState,
    OrchestrationPhase,
    OrchestrationStateError,
)
from app.tools.context import ExecutionContext
from app.tools.continuation_adapter import MockProviderContinuationAdapter
from app.tools.continuation_adapter_registry import ProviderContinuationAdapterRegistry
from app.tools.contracts import BaseTool, ToolCategory, ToolMetadata
from app.tools.registry import ToolRegistry
from app.tools.result import ToolError, ToolResult, ToolStatus
from app.tools.selection import ToolSelectionRequest, ToolSelectionResolver
from app.tools.tool_runtime import build_tool_continuation_runtime
from tests.tools.audit_fakes import RecordingAuditRepository


class ResilienceContinuationAdapter(MockProviderContinuationAdapter):
    @property
    def provider_name(self) -> str:
        return "resilience"


class ResilienceInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action: str
    value: str = "ok"


class ResilienceOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    value: str


class ResilienceTool(BaseTool[ResilienceInput, ResilienceOutput]):
    metadata = ToolMetadata(
        name="resilience_probe",
        version="1.0.0",
        description="Exercise deterministic orchestration failure boundaries.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("resilience_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
        is_enabled=True,
    )
    input_schema = ResilienceInput
    output_schema = ResilienceOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        if input_model.action == "timeout":
            raise TimeoutError("simulated tool timeout")
        if input_model.action == "cancel":
            raise CancelledError("simulated tool cancellation")
        if input_model.action == "interrupt":
            raise KeyboardInterrupt("simulated interruption")
        if input_model.action == "error":
            raise RuntimeError("simulated technical failure")
        if input_model.action == "failure":
            return ToolResult[ResilienceOutput](
                status=ToolStatus.FAILURE,
                error=ToolError(
                    error_code="probe_failure",
                    public_message="The probe could not be completed.",
                ),
            )
        return ToolResult[ResilienceOutput](
            status=ToolStatus.SUCCESS,
            data=ResilienceOutput(value=input_model.value),
        )


class ResilienceProvider(ModelProvider):
    def __init__(
        self, handler: Callable[[object], ModelToolLoopTurnResponse]
    ) -> None:
        self._handler = handler
        self.requests: list[object] = []
        self._lock = Lock()

    @property
    def provider_name(self) -> str:
        return "resilience"

    @property
    def model_name(self) -> str:
        return "resilience-model"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def generate(self, request: ModelRequest) -> ModelResponse:
        raise AssertionError("legacy generation is outside the bounded loop")

    def run_tool_loop_turn(self, request):  # type: ignore[no-untyped-def]
        with self._lock:
            self.requests.append(request)
        return self._handler(request)


def tool_turn(
    call_id: str,
    action: str = "success",
    value: str = "ok",
) -> ModelToolLoopTurnResponse:
    return ModelToolLoopTurnResponse(
        tool_calls=(
            ToolSelectionRequest(
                call_id=call_id,
                tool_name="resilience_probe",
                tool_version="1.0.0",
                arguments={"action": action, "value": value},
            ),
        ),
        assistant_content="Checking safely.",
    )


def final(content: str = "done") -> ModelToolLoopTurnResponse:
    return ModelToolLoopTurnResponse(
        final_response=ModelResponse(
            content=content,
            provider_name="resilience",
            model_name="resilience-model",
        )
    )


def context(message: str = "run probe") -> ConversationContext:
    return ConversationContext(
        system_instructions="Be deterministic.",
        messages=(
            ConversationMessage(role=ConversationRole.USER, content=message),
        ),
        provider_name="resilience",
        model_name="resilience-model",
    )


def execution_context():  # type: ignore[no-untyped-def]
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        conversation_id=uuid4(),
        model_name="resilience-model",
    )


def build(
    handler: Callable[[object], ModelToolLoopTurnResponse],
    trace_sink=None,  # type: ignore[no-untyped-def]
):
    tools = ToolRegistry()
    tools.register(ResilienceTool)
    adapters = ProviderContinuationAdapterRegistry()
    adapters.register("resilience", ResilienceContinuationAdapter())
    audit = RecordingAuditRepository()
    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=adapters,
        audit_repository=audit,
    )
    provider = ResilienceProvider(handler)
    providers = ProviderRegistry()
    providers.register(provider)
    states: list[OrchestrationExecutionState] = []

    def state_factory(trace_id):  # type: ignore[no-untyped-def]
        state = OrchestrationExecutionState(trace_id)
        states.append(state)
        return state

    service_kwargs = {}
    if trace_sink is not None:
        service_kwargs["trace_sink"] = trace_sink
    service = BoundedModelToolLoopService(
        provider_registry=providers,
        selection_resolver=ToolSelectionResolver(tools),
        tool_runtime=runtime,
        max_model_turns=4,
        timeout_seconds=30,
        state_factory=state_factory,
        **service_kwargs,
    )
    return service, provider, audit, states


def invoke(service, runtime_context=None, token=None):  # type: ignore[no-untyped-def]
    trusted = runtime_context or execution_context()
    return service.run(
        provider_name="resilience",
        model_name="resilience-model",
        context=context(),
        execution_context=trusted,
        cancellation_token=token,
    )


def test_provider_timeout_is_structured_and_state_is_cleaned() -> None:
    def timeout(_request):  # type: ignore[no-untyped-def]
        raise TimeoutError("provider exceeded its deadline")

    service, _, audit, states = build(timeout)
    result = invoke(service)

    assert result.termination_reason is ModelToolLoopTermination.TIMEOUT
    assert result.error_code == "provider_timeout"
    assert result.tools_executed == 0 and audit.started == []
    assert states[0].snapshot().phase is OrchestrationPhase.CLEANED
    assert states[0].snapshot().termination_reason == "timeout"


@pytest.mark.parametrize(
    ("action", "expected_code"),
    (("timeout", "tool_timeout"), ("cancel", "tool_cancelled")),
)
def test_tool_timeout_and_cancellation_finalize_audit_and_cleanup(
    action: str, expected_code: str
) -> None:
    service, _, audit, states = build(lambda _request: tool_turn("one", action))
    result = invoke(service)

    expected_reason = (
        ModelToolLoopTermination.TIMEOUT
        if action == "timeout"
        else ModelToolLoopTermination.CANCELLED
    )
    assert result.termination_reason is expected_reason
    assert result.error_code == expected_code
    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["status"] == "error"
    assert states[0].snapshot().phase is OrchestrationPhase.CLEANED


def test_provider_cooperative_cancellation_is_observed_after_provider_returns() -> None:
    token = OrchestrationCancellationToken()

    def cancel_during_provider(_request):  # type: ignore[no-untyped-def]
        token.cancel()
        return final("must not be returned")

    service, provider, _, states = build(cancel_during_provider)
    result = invoke(service, token=token)

    assert result.termination_reason is ModelToolLoopTermination.CANCELLED
    assert result.error_code == "provider_cancelled"
    assert len(provider.requests) == 1
    assert states[0].snapshot().phase is OrchestrationPhase.CLEANED


def test_interrupted_tool_execution_is_audited_and_does_not_escape() -> None:
    service, _, audit, states = build(
        lambda _request: tool_turn("interrupt", "interrupt")
    )
    result = invoke(service)

    assert result.termination_reason is ModelToolLoopTermination.CANCELLED
    assert result.error_code == "tool_cancelled"
    assert len(audit.started) == len(audit.finalized) == 1
    assert audit.finalized[0]["exception_type"] == "KeyboardInterrupt"
    assert states[0].snapshot().active_call_id is None


def test_business_failure_returns_safe_result_and_cleans_state() -> None:
    service, _, audit, states = build(
        lambda _request: tool_turn("business", "failure")
    )

    result = invoke(service)

    assert result.termination_reason is ModelToolLoopTermination.TOOL_BUSINESS_FAILURE
    assert result.error_code == "probe_failure"
    assert result.final_response.content == "The probe could not be completed."
    assert audit.finalized[0]["status"] == "failed"
    assert states[0].snapshot().phase is OrchestrationPhase.CLEANED


def test_duplicate_call_is_claimed_once_and_never_reexecuted() -> None:
    duplicate = tool_turn("same").tool_calls[0]

    def repeat(request):  # type: ignore[no-untyped-def]
        return ModelToolLoopTurnResponse(
            tool_calls=(duplicate,), assistant_content="duplicate"
        )

    service, provider, audit, states = build(
        repeat
    )
    result = invoke(service)

    assert result.termination_reason is ModelToolLoopTermination.INVALID_TOOL_CALL
    assert result.error_code == "duplicate_tool_call"
    assert result.tools_executed == 1
    assert len(audit.started) == len(audit.finalized) == 1
    assert len(provider.requests) == 2
    assert states[0].snapshot().claimed_call_ids == ("same",)


def test_partial_turn_failure_preserves_completed_work_without_continuation() -> None:
    first = tool_turn("first").tool_calls[0]
    second = tool_turn("second", "timeout").tool_calls[0]
    service, provider, audit, states = build(
        lambda _request: ModelToolLoopTurnResponse(
            tool_calls=(first, second), assistant_content="two calls"
        )
    )
    result = invoke(service)

    assert result.termination_reason is ModelToolLoopTermination.TIMEOUT
    assert [cycle.selection.call_id for cycle in result.tool_cycles] == ["first"]
    assert len(audit.started) == len(audit.finalized) == 2
    assert len(provider.requests) == 1
    snapshot = states[0].snapshot()
    assert snapshot.completed_call_ids == ("first",)
    assert snapshot.active_call_id is None


def test_fresh_run_recovers_after_previous_provider_failure() -> None:
    calls = 0

    def recover(request):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient provider failure")
        return final(f"recovered-{request.context.messages[0].content}")

    service, _, _, states = build(recover)
    failed = invoke(service)
    recovered = invoke(service)

    assert failed.termination_reason is ModelToolLoopTermination.PROVIDER_ERROR
    assert recovered.termination_reason is ModelToolLoopTermination.FINAL_RESPONSE
    assert recovered.final_response.content == "recovered-run probe"
    assert len(states) == 2
    assert states[0] is not states[1]
    assert all(s.snapshot().phase is OrchestrationPhase.CLEANED for s in states)


def test_concurrent_conversations_have_isolated_state_and_tool_calls() -> None:
    def deterministic(request):  # type: ignore[no-untyped-def]
        value = request.context.messages[0].content
        if request.turn_number == 1:
            return tool_turn(f"call-{value}", value=value)
        return final(f"finished-{value}")

    service, _, audit, states = build(deterministic)
    trusted = [execution_context(), execution_context()]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                service.run,
                provider_name="resilience",
                model_name="resilience-model",
                context=context(name),
                execution_context=trusted[index],
            )
            for index, name in enumerate(("alpha", "beta"))
        ]
        results = [future.result() for future in futures]

    assert {r.final_response.content for r in results} == {
        "finished-alpha",
        "finished-beta",
    }
    assert {r.tool_cycles[0].selection.call_id for r in results} == {
        "call-alpha",
        "call-beta",
    }
    assert len(audit.started) == len(audit.finalized) == 2
    assert {s.snapshot().trace_id for s in states} == {
        trusted[0].trace_id,
        trusted[1].trace_id,
    }
    assert all(s.snapshot().phase is OrchestrationPhase.CLEANED for s in states)


def test_trace_id_correlates_provider_tool_termination_and_cleanup(caplog) -> None:
    service, _, _, _ = build(
        lambda request: tool_turn("trace") if request.turn_number == 1 else final()
    )
    trusted = execution_context()

    with caplog.at_level("INFO"):
        result = invoke(service, runtime_context=trusted)

    assert result.completed
    correlated = [message for message in caplog.messages if str(trusted.trace_id) in message]
    assert any("provider_turn_started" in message for message in correlated)
    assert any("tool_execution_started" in message for message in correlated)
    assert any("event=termination" in message for message in correlated)
    assert any("event=cleanup" in message for message in correlated)


def test_execution_state_rejects_inconsistent_transitions() -> None:
    state = OrchestrationExecutionState(uuid4())
    with pytest.raises(OrchestrationStateError, match="expected phase"):
        state.finish_tool()
    state.begin_provider(1)
    with pytest.raises(OrchestrationStateError, match="expected phase"):
        state.begin_tool("call")
    state.finish_provider()
    state.begin_tool("call")
    state.finish_tool()
    with pytest.raises(OrchestrationStateError, match="already been claimed"):
        state.begin_tool("call")
    state.terminate("done")
    state.cleanup()
    assert state.snapshot().phase is OrchestrationPhase.CLEANED
