# Runtime Model Pipeline Wiring

Stage 7.9 adds the application composition root for the existing model pipeline:

```python
pipeline = build_model_pipeline()
```

```text
Settings
  + SQLAlchemy session factory -> ModelRunAuditRepository
  + OllamaQwenProvider          -> ProviderRegistry
  + OllamaPromptAdapter         -> PromptAdapterRegistry
                                      |
                                      v
                         ModelPipelineCoordinator
```

The factory validates required configuration before composition, obtains the
existing cached SQLAlchemy session factory, registers matching provider/adapter
pairs, creates the existing ModelRun write repository, and injects everything
into a persistence-enabled coordinator. Construction does not contact Ollama or
open a PostgreSQL connection.

Future providers can be supplied as interface-compatible provider/adapter pairs.
Names and model identities must match, and duplicate registration errors surface
immediately. No provider receives a repository and no persistence component
receives provider-specific transport details.
