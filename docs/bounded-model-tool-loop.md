# Stage 9 — Bounded Multi-Turn Tool Execution Loop

The bounded loop is the harness-owned coordinator for a finite sequence of
model turns and approved tool executions.

```text
ConversationContext
  -> registered ModelProvider
  -> normalized ModelToolLoopTurnResponse
  -> ToolSelectionResolver
  -> existing audited ToolContinuationRuntime
  -> ordered provider continuation payloads
  -> same ModelProvider
  -> terminal ModelResponse
```

## Ownership

- Providers translate their native response into the normalized turn contract.
- The loop controls iteration, ordering, limits, timeout checks, and termination.
- The existing resolver validates every model-generated argument against the
  registered tool schema.
- The existing tool runtime executes registered tools and owns ToolCall audit.
- Repositories remain the only database access layer used by business tools.

The loop never imports a function from model output and never executes an
unregistered tool. Tool calls run sequentially in provider order.

## Bounds and failures

`MAX_MODEL_TURNS` has a default of `5`. Reaching it returns a structured
`max_turns_reached` result. Provider, tool, invalid-call, timeout, and cancelled
terminations are also explicit and do not expose internal exception details.

Expected business failures are encoded in the existing `ToolResult` and passed
back to the model. Technical and corrupted-state failures terminate the loop.

## Current integration boundary

The live Ollama/Qwen adapter implements native tool-call translation and the
existing `/api/v1/model/invoke` route resolves the bounded-loop application
service through its normal dependency. Provider-native calls become normalized
tool selections before resolution; the HTTP route does not manufacture or
execute tool calls itself.

Continuation ModelRun persistence, streaming, parallel tool execution, provider
fallback, and autonomous planning remain out of scope.
