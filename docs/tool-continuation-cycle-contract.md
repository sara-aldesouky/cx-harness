# Provider-Neutral Tool-Continuation Cycle Contract

Stage 8.12 defines one immutable record of a completed tool-continuation cycle.

```text
ValidatedToolSelection
        |
        v
ToolExecutionRequest
        |
        v
ToolExecutionOutcome
        |
        v
ProviderContinuationPayload
        |
        v
ToolContinuationCycle
```

The cycle contains the existing typed contracts instead of copying their fields
into competing dictionaries. This preserves their validation, deep immutability,
serialization, and ownership boundaries while retaining the original instances.

Every artifact must have the same call ID. The selection, execution request, and
outcome must also have identical canonical tool names and resolved versions. The
selection's normalized arguments must equal the execution request arguments; the
factory compares their neutral JSON representations without revalidating a tool
schema.

The requested provider identity is stripped and lowercased and must match the
continuation payload envelope. Provider-specific nested payload data is not
parsed: formatting and status representation remain responsibilities of the
continuation adapter and service.

Only completed cycles are valid. Pending selections, running executions,
translation failures, unexpected executor exceptions, and missing continuation
payloads require a separate future lifecycle state model. An unexpected executor
exception cannot produce an outcome, so it cannot produce this completed cycle.

This is a contract and factory, not an orchestration service. A later service can
produce each artifact through its existing owner and pass those completed
artifacts to `ToolContinuationCycleFactory` for consistency verification. The
factory itself performs no lookup, execution, translation, provider invocation,
prompting, persistence, or network access.
