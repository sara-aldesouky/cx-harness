# Single Provider Tool-Call Cycle Service

Stage 8.15 adds the application boundary between raw provider tool-call data and
the existing execution-to-continuation runtime.

```text
provider + raw provider payload + trusted ExecutionContext
                         |
                         v
SingleProviderToolCallCycleService
             |                       |
             v                       v
   ToolSelectionService      ToolContinuationRuntime
             |                       |
             v                       v
 ValidatedToolSelection       completed cycle
                         |
                         v
              ToolContinuationCycle
```

This service begins with raw provider data because provider translation and tool
selection are the remaining application step immediately before Stage 8.13.
`ToolSelectionService` continues to own adapter lookup, provider translation,
tool lookup, enablement, and input-schema validation. Stage 8.13 is not duplicated:
the exact returned selection is passed directly to the composed runtime, which
owns execution, auditing, outcome creation, continuation translation, and cycle
construction.

Exactly one validated selection is required. Zero or multiple selections are
rejected; none are silently discarded, merged, or executed. The caller's same
provider identity flows into both selection and runtime execution, while existing
registries and cycle validation own normalization and consistency.

Selection failures stop before runtime invocation, so no tool execution or audit
lifecycle begins. A valid tool business failure is different: it completes the
runtime and is returned as a failure `ToolContinuationCycle`. Both selection and
runtime are invoked at most once, with no retry or fallback.

Model invocation and continuation remain outside this boundary. Multi-tool
ordering, partial success, parallel execution, and agent-loop policies are
deliberately deferred to a later stage.
