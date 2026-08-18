"""Explicit opt-in live check of local qwen3:8b bounded tool calling."""

import os
from uuid import uuid4

import pytest

from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.providers.ollama_qwen import (
    OllamaProviderContinuationAdapter,
    OllamaQwenProvider,
)
from app.providers.registry import ProviderRegistry
from app.services.model_tool_loop_service import BoundedModelToolLoopService
from app.tools.context import ExecutionContext
from app.tools.continuation_adapter_registry import ProviderContinuationAdapterRegistry
from app.tools.ping import PingTool
from app.tools.registry import ToolRegistry
from app.tools.tool_runtime import build_tool_continuation_runtime
from tests.tools.audit_fakes import RecordingAuditRepository
from tests.trusted_selection_fakes import trusted_selection_pipeline


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_TOOL_LOOP_INTEGRATION") != "1",
    reason="set RUN_OLLAMA_TOOL_LOOP_INTEGRATION=1 for local Ollama verification",
)


def test_local_qwen_executes_ping_and_returns_a_terminal_answer() -> None:
    """Use localhost Ollama and no database or external network dependency."""

    tools = ToolRegistry()
    tools.register(PingTool)
    provider = OllamaQwenProvider(tool_definitions=tools.definitions())
    providers = ProviderRegistry()
    providers.register(provider)
    continuations = ProviderContinuationAdapterRegistry()
    continuations.register("ollama", OllamaProviderContinuationAdapter())
    audit = RecordingAuditRepository()
    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
    )
    loop = BoundedModelToolLoopService(
        provider_registry=providers,
        trusted_selection_pipeline=trusted_selection_pipeline(tools),
        tool_runtime=runtime,
        max_model_turns=3,
        timeout_seconds=120,
    )

    result = loop.run(
        provider_name="ollama",
        model_name="qwen3:8b",
        context=ConversationContext(
            system_instructions=(
                "You must call the ping tool exactly once with message 'hello'. "
                "After receiving its result, answer in one short sentence."
            ),
            messages=(
                ConversationMessage(
                    role=ConversationRole.USER,
                    content="Please perform the required ping now.",
                ),
            ),
            provider_name="ollama",
            model_name="qwen3:8b",
        ),
        execution_context=ExecutionContext(
            trace_id=uuid4(), execution_id=uuid4(), conversation_id=uuid4(),
            customer_id=uuid4(), model_name="qwen3:8b"
        ),
    )

    assert result.completed
    assert result.provider_turns == 2
    assert result.tools_executed == 1
    assert result.tool_cycles[0].selection.tool_name == "ping"
    assert result.final_response is not None
    assert result.final_response.content
    assert len(audit.started) == len(audit.finalized) == 1
