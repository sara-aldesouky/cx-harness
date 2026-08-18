# Stage 14 — Provider-Neutral Model Orchestration

Stage 14 introduces an isolated model-orchestration boundary. It does not alter
the frozen Stage 13 binding or execution pipeline and is not yet composed into
the production conversation runtime.

## Architecture

```text
Conversation runtime (future composition)
  → ModelOrchestrator
  → ModelProviderAdapterRegistry
  → configured ModelProviderAdapter
  → provider transport or SDK
  → normalized ModelOrchestrationResponse
```

Only a concrete adapter may translate provider payloads, invoke an SDK or HTTP
transport, and interpret provider errors. The orchestrator contains no
provider-name branches, business policy, tool execution, schema validation,
authorization, binding, evaluation, or routing intelligence.

## Request contract

`ModelOrchestrationRequest` is immutable and contains:

- normalized system instructions;
- an ordered tuple of user, assistant, and tool messages;
- provider-neutral available-tool declarations;
- generation settings;
- correlation and execution metadata.

Tool definitions contain JSON Schema as deeply immutable JSON. They do not
contain provider function declarations. Tool-result messages preserve their
call IDs so an adapter can translate a continuation without runtime knowledge.

## Response contract

`ModelOrchestrationResponse` contains:

- an optional assistant message;
- ordered normalized tool selections;
- provider and model identity;
- provider request ID;
- normalized finish reason;
- input, output, and total token counts;
- measured orchestration latency;
- immutable safe provider metadata.

Tool selections are output only. Stage 14 never binds, validates, authorizes,
or executes them. A future composition step may translate them into the frozen
Stage 13.4 input boundary.

## Adapter boundary

Every adapter implements `ModelProviderAdapter`:

```text
provider_name
model_identifier
capabilities
supports_streaming
invoke(ModelOrchestrationRequest) → ModelOrchestrationResponse
```

`ModelProviderCapabilities` is an immutable neutral feature snapshot covering
tool calling, streaming, structured output, system instructions, image input,
multimodal input, and function calling. The orchestrator does not branch on
these fields. Callers or future composition code can validate compatibility
declaratively before invocation. `supports_streaming` remains a convenience
view over the streaming capability.

The existing request represents a complete normalized invocation and the
existing response represents its completed normalized result. A future
streaming API can emit separate event contracts around the same message, tool,
usage, finish-reason, and metadata models without changing either public
contract. Streaming itself is not implemented in Stage 14.

`FakeModelProviderAdapter` is deterministic, performs no I/O, and exists for
development and tests. Real Gemini, Ollama, or future adapters can implement
the same boundary without changing the orchestrator.

## Configuration and selection

`ModelOrchestratorConfiguration` selects an exact normalized provider name and
model identifier. `ModelProviderAdapterRegistry` resolves that provider
deterministically. Switching providers changes registrations and configuration,
not orchestration code. There is no automatic selection, fallback, A/B testing,
or routing policy.

## Error normalization

Adapters convert SDK failures to `ModelProviderAdapterError`. The orchestrator
exposes only `ModelOrchestrationError` with one of these categories:

- `timeout`
- `unavailable`
- `authentication_failure`
- `rate_limit`
- `malformed_provider_response`
- `provider_execution_failure`

Unexpected adapter exceptions are converted to a safe execution failure. Raw
SDK exception messages do not cross the orchestration boundary.

Cooperative cancellation is not a provider failure. Both `asyncio` and
`concurrent.futures` cancellation exceptions propagate immediately and are
never normalized into an error category.

## Dependency rules

The `app.model_orchestration` package depends only on its own contracts,
Pydantic, and Python standard-library types. It does not import the conversation
runtime, Stage 13, business tools, authorization, repositories, database code,
or any provider SDK.

Concrete provider adapters may depend inward on the Stage 14 contracts and
outward on their provider transport. Adapters must never import conversation or
tool execution runtime components.

## Future integration

A later explicitly scoped integration stage may compose the conversation
runtime with `ModelOrchestrator`. That integration must preserve the frozen
post-model flow:

```text
normalized tool selection
  → Stage 13.4 TrustedSelectionPipeline
  → schema validation
  → authorization
  → business execution
```

Stage 14 itself stops at normalized model output.
