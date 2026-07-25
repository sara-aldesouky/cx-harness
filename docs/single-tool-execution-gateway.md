# Single Tool Execution Gateway

Stage 8.7 adds a narrow application boundary over the existing `ToolExecutor`.

```text
ToolExecutionRequest
        |
        v
SingleToolExecutionGateway
        |
        +-- exact ToolRegistry lookup
        +-- current enablement check
        +-- Pydantic input-model rehydration
        |
        v
ToolExecutor
        |
        +-- exact registry resolution
        +-- audit row creation
        +-- tool construction
        +-- one invocation
        +-- result validation
        +-- audit finalization
        |
        v
ToolResult (unchanged)
```

Only `ToolExecutionRequest` crosses the gateway. Raw provider payloads,
`ToolSelectionRequest`, `ValidatedToolSelection`, tuples, and batches are
rejected. Canonical name and resolved version are always supplied together for
exact lookup; the gateway never falls back to another version or name-only
resolution.

Enablement is checked again because runtime configuration may change after
selection. This is a state-change safety check, not repeated selection logic.
Arguments are already validated; the gateway only rehydrates their immutable
JSON representation into the input-model instance required by `ToolExecutor`.

The existing executor remains the sole execution engine and the sole owner of
tool construction, result verification, timing, audit creation, persistence,
and finalization. The gateway creates no audit record, which prevents duplicate
records. Existing business failures and unexpected exceptions retain their
current executor semantics.

This boundary handles exactly one synchronous request. It does not implement
batching, parallelism, provider continuation, model re-invocation, prompts, or
an agent loop. The synchronous caller retains the request call ID for
correlation; the existing `ToolResult` and audit schema are intentionally not
redesigned in this stage.
