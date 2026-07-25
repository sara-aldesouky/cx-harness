# Model Invocation Persistence

Stage 7.8 integrates the existing `ModelRun` table into the provider-neutral
pipeline without exposing database details to adapters or providers.

```text
ModelPipelineCoordinator
  -> create running ModelRun
  -> execute the unchanged provider-neutral pipeline
  -> finalize completed or failed ModelRun
  -> return response or re-raise the original pipeline error
```

`ModelRunAuditRepository` is the narrow write boundary. Start and finish times
use UTC wall time; elapsed latency uses a monotonic clock. Persistence failures
raise `ModelRunPersistenceError` and never allow an untracked invocation to
start when initial creation fails.

## Existing-schema mapping

The existing table requires `conversation_id`, so persistence-enabled pipeline
runs require it. Customer identity remains available through the conversation's
existing customer relationship. The provider check allows `qwen` rather than
the transport name `ollama`, so local Ollama/Qwen calls persist as provider
`qwen` and retain the exact model name such as `qwen3:8b`.

The schema has one `error_message` column and no separate error-class or
response-metadata columns. Failures therefore store `ErrorClass: message` in
that field. Response identity is already represented by provider and model;
tokens, cost, and temperature remain null when unavailable. No schema or
migration was added.
