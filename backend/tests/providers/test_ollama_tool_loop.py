"""Mocked-HTTP integration tests for Ollama and the real bounded loop."""

from __future__ import annotations

import json
from collections import deque
from uuid import uuid4

import httpx
import pytest

from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.api.dependencies import get_model_invocation_mapper
from app.providers.ollama_qwen import (
    OllamaProviderContinuationAdapter,
    OllamaQwenProvider,
)
from app.providers.registry import ProviderRegistry
from app.services.model_tool_loop_service import (
    BoundedModelToolLoopService,
    ModelToolLoopTermination,
    ModelToolLoopApplicationService,
)
from app.tools.context import ExecutionContext
from app.tools.continuation_adapter_registry import ProviderContinuationAdapterRegistry
from app.tools.ping import PingTool
from app.tools.registry import ToolRegistry
from app.tools.selection import ToolSelectionResolver
from app.tools.tool_runtime import build_tool_continuation_runtime
from tests.tools.audit_fakes import RecordingAuditRepository


def response(*, content="", tool_calls=None):  # type: ignore[no-untyped-def]
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"message": message}


def native_call(name="ping", message="hello", call_id=None):  # type: ignore[no-untyped-def]
    value = {
        "type": "function",
        "function": {"name": name, "arguments": {"message": message}},
    }
    if call_id is not None:
        value["id"] = call_id
    return value


def build_loop(responses):  # type: ignore[no-untyped-def]
    queued = deque(responses)
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        item = queued.popleft()
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)

    tools = ToolRegistry()
    tools.register(PingTool)
    provider = OllamaQwenProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        tool_definitions=tools.definitions(),
    )
    providers = ProviderRegistry()
    providers.register(provider)
    adapters = ProviderContinuationAdapterRegistry()
    adapters.register("ollama", OllamaProviderContinuationAdapter())
    audit = RecordingAuditRepository()
    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=adapters,
        audit_repository=audit,
    )
    loop = BoundedModelToolLoopService(
        provider_registry=providers,
        selection_resolver=ToolSelectionResolver(tools),
        tool_runtime=runtime,
    )
    return loop, requests, audit


def run(loop):  # type: ignore[no-untyped-def]
    return loop.run(
        provider_name="ollama",
        model_name="qwen3:8b",
        context=ConversationContext(
            system_instructions="Use approved tools when needed.",
            messages=(
                ConversationMessage(
                    role=ConversationRole.USER,
                    content="Ping twice if needed.",
                ),
            ),
            provider_name="ollama",
            model_name="qwen3:8b",
        ),
        execution_context=ExecutionContext(
            trace_id=uuid4(), execution_id=uuid4(), model_name="qwen3:8b"
        ),
    )


def test_real_provider_returns_immediate_final_response() -> None:
    loop, requests, audit = build_loop([response(content="Finished")])
    result = run(loop)

    assert result.completed
    assert result.final_response.content == "Finished"
    assert result.provider_turns == 1 and result.tools_executed == 0
    assert not audit.started
    assert requests[0]["model"] == "qwen3:8b"
    assert requests[0]["tools"][0]["function"]["name"] == "ping"


def test_one_native_tool_call_continues_with_assistant_call_and_result() -> None:
    loop, requests, audit = build_loop(
        [
            response(tool_calls=[native_call(call_id="native-1")]),
            response(content="Pong received."),
        ]
    )
    result = run(loop)

    assert result.completed and result.tools_executed == 1
    assert result.tool_cycles[0].selection.call_id == "native-1"
    assert len(audit.started) == len(audit.finalized) == 1
    continuation_messages = requests[1]["messages"]
    assistant = next(message for message in continuation_messages if message["role"] == "assistant")
    tool = next(message for message in continuation_messages if message["role"] == "tool")
    assert assistant["tool_calls"][0]["id"] == "native-1"
    assert assistant["tool_calls"][0]["function"]["arguments"] == {"message": "hello"}
    assert tool["tool_name"] == "ping"
    assert '"status":"success"' in tool["content"]


def test_multiple_calls_preserve_native_order_and_ids() -> None:
    loop, requests, _ = build_loop(
        [
            response(
                tool_calls=[
                    native_call(message="first", call_id="a"),
                    native_call(message="second", call_id="b"),
                ]
            ),
            response(content="Both complete."),
        ]
    )
    result = run(loop)

    assert [cycle.selection.call_id for cycle in result.tool_cycles] == ["a", "b"]
    continuation = requests[1]["messages"]
    assistant = next(message for message in continuation if message["role"] == "assistant")
    assert [call["id"] for call in assistant["tool_calls"]] == ["a", "b"]
    assert [m["tool_name"] for m in continuation if m["role"] == "tool"] == ["ping", "ping"]


def test_consecutive_tool_turns_reconstruct_complete_history() -> None:
    loop, requests, _ = build_loop(
        [
            response(tool_calls=[native_call(message="first", call_id="a")]),
            response(tool_calls=[native_call(message="second", call_id="b")]),
            response(content="Complete."),
        ]
    )
    result = run(loop)

    assert result.termination_reason is ModelToolLoopTermination.FINAL_RESPONSE
    assert result.provider_turns == 3 and result.tools_executed == 2
    final_messages = requests[2]["messages"]
    assistant_calls = [m for m in final_messages if m["role"] == "assistant"]
    assert [m["tool_calls"][0]["id"] for m in assistant_calls] == ["a", "b"]


def test_missing_native_id_is_rejected_as_malformed_provider_output() -> None:
    loop, _, _ = build_loop(
        [response(tool_calls=[native_call()]), response(content="Done")]
    )
    result = run(loop)

    assert result.termination_reason is ModelToolLoopTermination.PROVIDER_ERROR
    assert result.tool_cycles == ()
    assert result.tools_executed == 0


@pytest.mark.parametrize(
    "malformed_response",
    [
        {},
        {"message": []},
        response(tool_calls={}),
        response(tool_calls=[{"id": "call-1"}]),
        response(
            tool_calls=[
                {
                    "id": "call-1",
                    "function": {"name": "", "arguments": {}},
                }
            ]
        ),
        response(
            tool_calls=[
                {
                    "id": "call-1",
                    "function": {"name": "ping", "arguments": []},
                }
            ]
        ),
    ],
)
def test_malformed_provider_payload_never_executes_tools(
    malformed_response,
) -> None:  # type: ignore[no-untyped-def]
    loop, _, audit = build_loop([malformed_response])

    result = run(loop)

    assert result.termination_reason is ModelToolLoopTermination.PROVIDER_ERROR
    assert result.tools_executed == 0
    assert audit.started == []


@pytest.mark.parametrize(
    ("failure", "termination", "error_code"),
    [
        (
            httpx.ConnectError("connection refused"),
            ModelToolLoopTermination.PROVIDER_ERROR,
            "provider_error",
        ),
        (
            httpx.ReadTimeout("read deadline exceeded"),
            ModelToolLoopTermination.TIMEOUT,
            "provider_timeout",
        ),
        (
            httpx.Response(200, content=b'{"message":'),
            ModelToolLoopTermination.PROVIDER_ERROR,
            "provider_error",
        ),
        (
            httpx.Response(200, json={"message": {"role": "assistant"}}),
            ModelToolLoopTermination.PROVIDER_ERROR,
            "provider_error",
        ),
    ],
)
def test_provider_transport_and_partial_response_failures_are_structured(
    failure, termination, error_code,
) -> None:  # type: ignore[no-untyped-def]
    loop, _, audit = build_loop([failure])

    result = run(loop)

    assert result.termination_reason is termination
    assert result.error_code == error_code
    assert result.tools_executed == 0
    assert audit.started == []


def test_http_dependency_is_wired_to_bounded_loop_application_service() -> None:
    get_model_invocation_mapper.cache_clear()
    mapper = get_model_invocation_mapper()

    assert isinstance(mapper._service, ModelToolLoopApplicationService)
