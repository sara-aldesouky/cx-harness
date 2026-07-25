# Tool-Continuation Runtime Composition

Stage 8.14 provides an application composition boundary for one ready-to-use
single-cycle orchestration service.

```text
ToolRegistry + ContinuationAdapterRegistry + AuditRepository
                           |
                           v
          build_tool_continuation_runtime(...)
                           |
                           v
              ToolContinuationRuntime
                           |
                           v
        SingleToolContinuationCycleService
```

Composition is separate from orchestration: the builder assembles objects, while
`cycle_service.run()` performs the lifecycle later. Callers must explicitly
supply a populated `ToolRegistry`, a populated
`ProviderContinuationAdapterRegistry`, and an audit lifecycle implementing
`create_running()` and `finalize()`. Tests can therefore replace persistence with
the existing in-memory audit fake without changing application code.

The builder constructs `ToolExecutor`, `SingleToolExecutionGateway`, request and
outcome factories, `ProviderContinuationService`, the cycle factory, and the
single-cycle service. Construction performs no registration, lookup, execution,
audit write, translation, cycle creation, environment loading, database
connection, or network access.

Registries are never populated automatically: the caller owns tool and adapter
availability. Their original instances, along with the original audit dependency,
are preserved throughout the internal graph. Each builder call returns an
independent frozen runtime container and a new service graph; no module-level
runtime or mutable global registry is introduced.

The public runtime deliberately exposes only `cycle_service`. A later application
runtime can consume that service through this stable composition API without
depending on every internal component.
