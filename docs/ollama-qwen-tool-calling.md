# Stage 9.2 — Local Ollama/Qwen Tool Calling

The existing bounded Stage 9.1 loop now uses the local Ollama `/api/chat`
protocol with `qwen3:8b`.

```text
POST /api/v1/model/invoke
  -> ModelToolLoopApplicationService
  -> BoundedModelToolLoopService
  -> OllamaQwenProvider
  -> http://localhost:11434/api/chat
  -> normalized tool selections
  -> existing resolver and audited tool runtime
  -> Ollama continuation messages
  -> final ModelInvocationResponse
```

## Translation

Enabled tool metadata is translated into Ollama function declarations. Native
Ollama calls are normalized into `ToolSelectionRequest` objects without registry
lookup or execution inside the provider. The harness then validates and executes
them in returned order.

Continuation requests contain the original assistant `tool_calls` message,
followed by ordered `role: tool` results with `tool_name` and JSON content. This
matches Ollama's documented single, parallel, and multi-turn tool-call protocol:
<https://docs.ollama.com/capabilities/tool-calling>.

## Limitations

- The configured model remains local `qwen3:8b`; no hosted Qwen API is used.
- Native tool-call IDs are required and preserved. A missing or malformed ID is
  rejected as malformed provider output and never reaches tool execution.
- Stage 9 executes calls sequentially even when Ollama returns a batch.
- Only `get_order_status` is registered in the default application runtime.
- The bounded-loop application service resolves trusted customer identity from
  the server-side conversation record. Customer identity never comes from the
  public request's model-generated tool arguments. Full HTTP authentication and
  authorization remain future application-boundary work.
- ModelRun persistence for continuation turns remains deferred; ToolCall audit
  remains active through the existing executor.
- Streaming, retries, fallback providers, and autonomous planning are absent.

## Verification

Mocked HTTP integration runs in the default suite. The real local test is gated:

```bash
RUN_OLLAMA_TOOL_LOOP_INTEGRATION=1 \
  .venv/bin/python -m pytest \
  tests/providers/integration/test_ollama_tool_loop_live.py -q
```

The live test uses localhost Ollama. Database configuration must still point to
the guarded local test database and never to Render.
