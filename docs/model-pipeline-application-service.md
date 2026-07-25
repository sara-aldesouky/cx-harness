# Model Pipeline Application Service

Stage 7.10 adds a framework-independent application boundary for future HTTP,
CLI, evaluation, and test entry points.

```text
Trusted conversation ID + history + current user message + instructions
                              |
                              v
                   ModelPipelineService
                              |
                   ContextBuilder validation
                              |
                              v
                one ModelPipelineCoordinator.run()
                              |
                              v
                 ModelPipelineServiceResult
```

The service appends the current user message after the supplied ordered history,
builds an immutable context, lazily obtains the runtime pipeline when one is not
injected, and performs exactly one coordinator invocation. ModelRun persistence
remains entirely inside the coordinator.

The immutable application result exposes only response content, provider name,
and model name. It does not expose SQLAlchemy sessions, repositories, registries,
Ollama payloads, or other transport details. Construction itself performs no
database or network work.
