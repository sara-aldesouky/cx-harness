"""Stage 9.4 execution-trace and diagnostics tests."""

from __future__ import annotations

from concurrent.futures import CancelledError, ThreadPoolExecutor

import pytest

from app.providers.base import ModelToolLoopTurnResponse
from app.services.orchestration_trace import (
    OrchestrationExecutionTrace,
    OrchestrationTimelineEventType,
    ProviderResponseType,
)
from tests.services.test_orchestration_resilience import (
    build,
    context,
    execution_context,
    final,
    invoke,
    tool_turn,
)


def captured_service(handler):  # type: ignore[no-untyped-def]
    traces: list[OrchestrationExecutionTrace] = []
    service, provider, audit, states = build(handler, trace_sink=traces.append)
    return service, provider, audit, states, traces


def test_successful_execution_publishes_complete_immutable_trace() -> None:
    service, _, _, _, traces = captured_service(lambda _request: final("hello"))
    trusted = execution_context()

    result = invoke(service, runtime_context=trusted)

    assert result.completed and len(traces) == 1
    trace = traces[0]
    assert trace.trace_id == trusted.trace_id
    assert trace.conversation_id == trusted.conversation_id
    assert trace.provider_name == "resilience"
    assert trace.model_name == "resilience-model"
    assert trace.ended_at >= trace.started_at
    assert trace.duration_ms >= 0
    assert trace.termination_reason == "final_response"
    assert trace.completed is True
    assert trace.provider_turns[0].response_type is ProviderResponseType.FINAL_RESPONSE
    assert trace.diagnostics.cleanup_completed is True
    assert trace.model_dump(mode="json")["trace_id"] == str(trusted.trace_id)
    with pytest.raises(Exception):
        trace.completed = False


def test_multi_turn_multi_tool_trace_has_chronological_timeline() -> None:
    first = tool_turn("first", value="a").tool_calls[0]
    second = tool_turn("second", value="b").tool_calls[0]

    def handler(request):  # type: ignore[no-untyped-def]
        if request.turn_number == 1:
            return ModelToolLoopTurnResponse(
                tool_calls=(first, second), assistant_content="checking"
            )
        return final("combined")

    service, _, _, _, traces = captured_service(handler)
    result = invoke(service)
    trace = traces[0]

    assert result.provider_turns == 2 and result.tools_executed == 2
    assert [turn.turn_number for turn in trace.provider_turns] == [1, 2]
    assert trace.provider_turns[0].tool_calls_requested == 2
    assert trace.provider_turns[1].response_type is ProviderResponseType.FINAL_RESPONSE
    assert [tool.tool_call_id for tool in trace.tool_executions] == ["first", "second"]
    assert all(tool.success for tool in trace.tool_executions)
    assert [event.sequence for event in trace.timeline] == list(
        range(1, len(trace.timeline) + 1)
    )
    assert [event.occurred_at for event in trace.timeline] == sorted(
        event.occurred_at for event in trace.timeline
    )
    assert [event.event_type for event in trace.timeline] == [
        OrchestrationTimelineEventType.REQUEST_RECEIVED,
        OrchestrationTimelineEventType.PROVIDER_TURN_STARTED,
        OrchestrationTimelineEventType.PROVIDER_TURN_FINISHED,
        OrchestrationTimelineEventType.TOOL_EXECUTION_STARTED,
        OrchestrationTimelineEventType.TOOL_EXECUTION_FINISHED,
        OrchestrationTimelineEventType.TOOL_EXECUTION_STARTED,
        OrchestrationTimelineEventType.TOOL_EXECUTION_FINISHED,
        OrchestrationTimelineEventType.PROVIDER_TURN_STARTED,
        OrchestrationTimelineEventType.PROVIDER_TURN_FINISHED,
        OrchestrationTimelineEventType.FINAL_RESPONSE,
        OrchestrationTimelineEventType.TERMINATION,
        OrchestrationTimelineEventType.CLEANUP,
    ]
    assert trace.diagnostics.provider_turns == 2
    assert trace.diagnostics.tools_executed == 2
    assert trace.diagnostics.total_provider_time_ms >= 0
    assert trace.diagnostics.total_tool_time_ms >= 0


def test_provider_timeout_trace_contains_safe_error_diagnostics() -> None:
    def timeout(_request):  # type: ignore[no-untyped-def]
        raise TimeoutError("private provider timeout detail")

    service, _, _, _, traces = captured_service(timeout)
    result = invoke(service)
    trace = traces[0]

    assert result.error_code == "provider_timeout"
    assert trace.termination_reason == "timeout"
    assert trace.provider_turns[0].success is False
    assert trace.provider_turns[0].error_code == "provider_timeout"
    assert trace.provider_turns[0].error_type == "TimeoutError"
    assert trace.diagnostics.error_summary == "provider_timeout"
    assert "private" not in trace.model_dump_json()


def test_provider_cancellation_trace_is_complete() -> None:
    def cancel(_request):  # type: ignore[no-untyped-def]
        raise CancelledError("private cancellation detail")

    service, _, _, _, traces = captured_service(cancel)
    result = invoke(service)
    trace = traces[0]

    assert result.error_code == "provider_cancelled"
    assert trace.termination_reason == "cancelled"
    assert trace.provider_turns[0].error_type == "CancelledError"
    assert trace.timeline[-1].event_type is OrchestrationTimelineEventType.CLEANUP


def test_provider_failure_trace_records_type_without_exception_message() -> None:
    def fail(_request):  # type: ignore[no-untyped-def]
        raise RuntimeError("database password must never appear")

    service, _, _, _, traces = captured_service(fail)
    result = invoke(service)
    trace = traces[0]

    assert result.error_code == "provider_error"
    assert trace.provider_turns[0].error_type == "RuntimeError"
    assert trace.provider_turns[0].response_type is ProviderResponseType.ERROR
    assert "password" not in trace.model_dump_json()


@pytest.mark.parametrize(
    ("action", "termination", "technical_type"),
    (
        ("timeout", "timeout", "TimeoutError"),
        ("cancel", "cancelled", "CancelledError"),
        ("error", "tool_error", "ToolCycleExecutionError"),
    ),
)
def test_tool_failure_traces_are_structured(
    action: str, termination: str, technical_type: str
) -> None:
    service, _, audit, _, traces = captured_service(
        lambda _request: tool_turn("tool-failure", action)
    )
    result = invoke(service)
    trace = traces[0]

    assert result.termination_reason.value == termination
    assert len(trace.tool_executions) == 1
    tool = trace.tool_executions[0]
    assert tool.success is False
    assert tool.technical_error_type == technical_type
    assert tool.business_failure_code is None
    assert len(audit.started) == len(audit.finalized) == 1
    assert trace.diagnostics.cleanup_completed


def test_business_failure_trace_records_public_code() -> None:
    service, _, _, _, traces = captured_service(
        lambda _request: tool_turn("business", "failure")
    )
    result = invoke(service)
    trace = traces[0]

    assert result.error_code == "probe_failure"
    assert trace.tool_executions[0].success is False
    assert trace.tool_executions[0].business_failure_code == "probe_failure"
    assert trace.tool_executions[0].technical_error_type is None
    assert trace.diagnostics.error_summary == "probe_failure"


def test_structured_logs_include_identity_without_customer_message(caplog) -> None:
    sensitive_message = "my secret account value is 12345"
    service, _, _, _, _ = captured_service(lambda _request: final())
    trusted = execution_context()

    with caplog.at_level("INFO"):
        service.run(
            provider_name="resilience",
            model_name="resilience-model",
            context=context(sensitive_message),
            execution_context=trusted,
        )

    correlated = [message for message in caplog.messages if str(trusted.trace_id) in message]
    assert correlated
    assert all(f"conversation_id={trusted.conversation_id}" in message for message in correlated)
    assert all("provider=resilience" in message for message in correlated)
    assert all("model=resilience-model" in message for message in correlated)
    assert all("provider_turn=" in message for message in correlated)
    assert all("tool_call_id=" in message for message in correlated)
    assert all(sensitive_message not in message for message in correlated)


def test_concurrent_execution_traces_are_isolated() -> None:
    traces: list[OrchestrationExecutionTrace] = []

    def handler(request):  # type: ignore[no-untyped-def]
        value = request.context.messages[0].content
        return tool_turn(f"call-{value}", value=value) if request.turn_number == 1 else final(value)

    service, _, _, _ = build(handler, trace_sink=traces.append)
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
            for index, name in enumerate(("one", "two"))
        ]
        [future.result() for future in futures]

    assert len(traces) == 2
    assert {trace.trace_id for trace in traces} == {item.trace_id for item in trusted}
    assert {trace.conversation_id for trace in traces} == {
        item.conversation_id for item in trusted
    }
    for trace in traces:
        assert len(trace.provider_turns) == 2
        assert len(trace.tool_executions) == 1
        assert trace.diagnostics.cleanup_completed


def test_trace_sink_failure_never_changes_orchestration_result(caplog) -> None:
    def broken_sink(_trace):  # type: ignore[no-untyped-def]
        raise RuntimeError("telemetry backend unavailable")

    service, _, _, _ = build(lambda _request: final("safe"), trace_sink=broken_sink)

    with caplog.at_level("ERROR"):
        result = invoke(service)

    assert result.completed and result.final_response.content == "safe"
    assert any("orchestration_trace_sink_failed" in message for message in caplog.messages)
