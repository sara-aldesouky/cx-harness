# Single Tool-Continuation Cycle Orchestration Service

Stage 8.13 coordinates one already-validated selection through the existing
execution-to-continuation boundaries.

```text
provider + ValidatedToolSelection + ExecutionContext
                         |
                         v
SingleToolContinuationCycleService
                         |
                         +-- ToolExecutionRequestFactory
                         +-- SingleToolExecutionGateway
                         +-- ToolExecutionOutcomeFactory
                         +-- ProviderContinuationService
                         +-- ToolContinuationCycleFactory
                         |
                         v
              ToolContinuationCycle
```

The service owns only lifecycle ordering and fail-fast delegation. Request
construction, tool lookup and execution, audit persistence, outcome correlation,
provider continuation translation, and final artifact validation remain owned by
their existing components. Input begins at `ValidatedToolSelection` because raw
provider translation and schema validation have already completed upstream.

Each dependency is called exactly once in request, execution, outcome,
continuation, and cycle order. Every produced artifact is passed directly to the
next boundary without reconstruction. No stage is retried.

A valid business-failure `ToolResult` is completed execution, so it continues to
a failure outcome, continuation payload, and completed cycle. Unexpected errors
stop immediately, are wrapped by lifecycle stage with their causes retained, and
prevent later components from running. No partial cycle is returned.

Orchestration atomicity is not database or external-side-effect atomicity. If
execution completes and continuation translation later fails, this service does
not undo execution or its audit record. It provides no rollback, compensation,
idempotency, or distributed transaction guarantees. The existing `ToolExecutor`
remains the sole owner of audit creation and finalization; this service adds no
audit writes.

One-selection synchronous scope is deliberate: multi-call ordering, partial
success, concurrency, retries, and compensation need explicit future policies.
Model and provider invocation remain outside this service, which only prepares a
completed continuation cycle for a future caller.
