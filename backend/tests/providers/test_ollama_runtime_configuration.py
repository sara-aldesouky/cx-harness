"""Ollama-only generation, retention, metadata, and prewarm behavior."""

import json
from uuid import uuid4

import httpx
import pytest

from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.harness.production_prompt import PRODUCTION_SYSTEM_PROMPT
from app.providers.base import ModelRequest
from app.providers.mock import MockModelProvider
from app.providers.ollama_qwen import (
    OllamaQwenProvider,
    OllamaRequestTimeoutError,
)
from app.services.model_tool_loop_service import ModelToolLoopTurnRequest
from app.tools.ping import PingTool


def turn_request() -> ModelToolLoopTurnRequest:
    return ModelToolLoopTurnRequest(
        provider_name="ollama",
        model_name="qwen3:8b",
        context=ConversationContext(
            system_instructions=PRODUCTION_SYSTEM_PROMPT,
            messages=(
                ConversationMessage(
                    role=ConversationRole.USER,
                    content="فين الأوردر؟",
                ),
            ),
            provider_name="ollama",
            model_name="qwen3:8b",
        ),
        turn_number=1,
    )


def test_tool_turn_sends_benchmark_ollama_options_and_safe_metadata() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "تمام"},
                "prompt_eval_count": 4134,
                "eval_count": 12,
                "load_duration": 100_000_000,
            },
        )

    provider = OllamaQwenProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        tool_definitions=(PingTool.definition(),),
        read_timeout_seconds=120,
        context_size=8192,
        max_output_tokens=256,
        keep_alive="20m",
        tool_thinking_enabled=False,
    )
    response = provider.run_tool_loop_turn(turn_request())

    assert response.final_response.content == "تمام"
    assert captured["think"] is False
    assert captured["options"] == {"num_ctx": 8192, "num_predict": 256}
    assert captured["keep_alive"] == "20m"
    assert captured["stream"] is False
    metadata = provider.last_invocation_metadata
    assert metadata.thinking_enabled is False
    assert metadata.context_size == 8192
    assert metadata.output_token_cap == 256
    assert metadata.timeout_seconds == 120
    assert metadata.keep_alive == "20m"
    assert metadata.cache_state == "warm"
    assert metadata.prompt_tokens == 4134
    assert metadata.output_tokens == 12


def test_timeout_is_one_provider_call_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    provider = OllamaQwenProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        tool_definitions=(PingTool.definition(),),
        read_timeout_seconds=37,
    )
    with pytest.raises(OllamaRequestTimeoutError):
        provider.run_tool_loop_turn(turn_request())

    assert calls == 1
    assert provider.last_invocation_metadata.timeout_seconds == 37
    assert provider.last_invocation_metadata.outcome == "timeout"


def test_prewarm_is_provider_only_and_cannot_execute_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def forbidden_database_factory():
        raise AssertionError("prewarm must not access the database")

    monkeypatch.setattr(
        "app.database.session.get_session_factory",
        forbidden_database_factory,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "prewarm-call",
                            "type": "function",
                            "function": {
                                "name": "ping",
                                "arguments": {"message": "ready"},
                            },
                        }
                    ],
                },
                "prompt_eval_count": 4100,
                "eval_count": 20,
                "load_duration": 2_000_000_000,
            },
        )

    provider = OllamaQwenProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        tool_definitions=(PingTool.definition(),),
    )
    metadata = provider.prewarm()

    assert len(calls) == 1
    assert calls[0]["messages"][0] == {
        "role": "system",
        "content": PRODUCTION_SYSTEM_PROMPT,
    }
    assert calls[0]["think"] is False
    assert calls[0]["tools"][0]["function"]["name"] == "ping"
    assert metadata.cache_state == "cold"


def test_non_tool_ollama_and_other_provider_behavior_remain_separate() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "ok"}},
        )

    ollama = OllamaQwenProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert ollama.generate(ModelRequest(prompt="hello")).content == "ok"
    assert "think" not in captured

    mock = MockModelProvider()
    assert mock.generate(ModelRequest(prompt="hello")).provider_name == "mock"
    assert not hasattr(mock, "context_size")


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        ({"context_size": 2048}, ValueError),
        ({"max_output_tokens": 0}, ValueError),
        ({"keep_alive": " "}, ValueError),
        ({"tool_thinking_enabled": "false"}, TypeError),
    ],
)
def test_invalid_provider_configuration_fails_fast(kwargs, error_type) -> None:
    with pytest.raises(error_type):
        OllamaQwenProvider(**kwargs)
