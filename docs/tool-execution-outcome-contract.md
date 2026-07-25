# Tool Execution Outcome Contract

Stage 8.8 correlates the existing executor result with the original provider
call without changing execution semantics.

```text
ToolExecutionRequest (call ID + canonical identity)
        |
SingleToolExecutionGateway
        |
ToolResult (success or safe business failure)
        |
        +---------------- ToolExecutionRequest
        |
ToolExecutionOutcomeFactory
        |
ToolExecutionOutcome
```

`ToolResult` remains the contract returned by tools and `ToolExecutor`.
`ToolExecutionOutcome` exists separately because `ToolResult` intentionally has
no provider call ID or tool identity. The factory restores correlation only from
the trusted `ToolExecutionRequest`; it never accepts an arbitrary call ID.

Success outcomes contain structured, recursively frozen JSON output. Business
failures retain only the existing safe `ToolError` code and public message.
Unexpected executor exceptions are re-raised before a `ToolResult` exists, so
they do not produce an outcome in this stage.

The current base `ToolResult` has no name or version to compare. If a compatible
result subtype explicitly exposes `tool_name` or `tool_version`, the factory
verifies those fields and rejects conflicts rather than silently overwriting
them. Timing, execution IDs, trace IDs, and audit references are not invented
because the current result contract does not provide them.

The outcome remains provider neutral. Formatting it into an Ollama, OpenAI,
Gemini, or other continuation message is a later adapter responsibility. The
factory performs no execution, auditing, persistence, model invocation, prompt
generation, or continuation.
