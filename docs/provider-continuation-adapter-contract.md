# Provider Continuation Adapter Contract

Stage 8.9 separates tool execution from provider continuation formatting.

```text
ToolExecutionOutcome
        |
        v
ProviderContinuationAdapter
        |
        v
ProviderContinuationPayload
        |
        v
Future provider re-invocation
```

Only `ToolExecutionOutcome` is accepted because it already contains canonical
tool identity, restored provider call correlation, structured success data, or
safe business-failure information. Raw tool results and provider payloads do not
cross this boundary.

`ProviderContinuationPayload` is a narrow immutable envelope containing the
provider identity, correlated call ID, and adapter-owned JSON payload. It does
not attempt to define one universal provider message schema.

`MockProviderContinuationAdapter` emits a deterministic test-only
`tool_result` protocol. Success contains structured output and no error field.
Business failure contains the safe error code and public message and no output
field. It never converts tool data into conversational prose.

The mock protocol is not an Ollama, OpenAI, Gemini, or other real provider
format. Each future provider owns its translation inside its adapter. Model
re-invocation is deferred because this stage owns formatting only: it does not
execute tools, call providers, generate prompts, write audits, or create an
agent loop.
