# Model Invocation API Contract

Stage 7.12 defines transport-neutral public schemas and mapping without adding a
FastAPI route:

```text
ModelInvocationRequest -> ModelInvocationMapper -> ModelPipelineService
  -> ModelPipelineServiceResult -> ModelInvocationResponse
```

The request exposes only conversation ID, current user message, ordered role and
content history, and optional system instructions. If instructions are omitted,
the mapper uses an explicitly injected application default; the contract does
not invent prompt content.

The immutable response exposes only content, provider name, and model name.
Persistence records, SQLAlchemy objects, registries, internal IDs, latency, and
Ollama payloads remain private. The mapper imports no FastAPI classes, performs
no HTTP translation, and preserves application-service exceptions for a future
route-level error policy.
