# Stage 9.4 — Orchestration Observability and Execution Trace

Stage 9.4 adds provider-neutral observability around the existing bounded
orchestration behavior. It does not change model, tool-selection, execution,
continuation, or result contracts and introduces no persistence schema.

## Trace lifecycle

Each `BoundedModelToolLoopService.run()` creates one run-local
`OrchestrationTraceRecorder` from trusted execution identity. The recorder is
never shared between conversations. After orchestration terminates, cleanup runs
in `finally`, an immutable `OrchestrationExecutionTrace` is built, and that trace
is published to the configured sink.

```text
Request Received
  → Provider Turn Started
  → Provider Turn Finished
  → Tool Execution Started (zero or more)
  → Tool Execution Finished
  → Provider Turn Started
  → Final Response
  → Termination
  → Cleanup
  → Immutable Trace Publication
```

Trace-sink failures are logged and isolated. They never replace or alter the
model-loop result.

## Execution trace

The immutable trace records:

- trusted trace and optional conversation IDs;
- normalized provider and model identity;
- UTC start/end timestamps and monotonic total duration;
- completion state and termination reason;
- ordered provider-turn records;
- ordered tool-execution records;
- a chronological timeline;
- a diagnostic summary.

The trace supports Pydantic JSON serialization and contains no prompts, model
response content, tool arguments, tool output, customer identity, credentials,
connection strings, or raw exception messages.

## Provider turns

Every provider turn includes its number, UTC boundaries, monotonic duration,
response type, requested-tool count, success state, and safe error code/type.
Response types are `final_response`, `tool_calls`, `invalid`, and `error`.

Timeouts, cancellations, invalid responses, provider identity mismatches, and
technical failures finish the active provider record before orchestration
termination.

## Tool executions

A tool trace begins only after selection and input validation succeed and the
tool is about to execute. It records the provider turn, tool name, call ID,
timestamps, duration, success state, a safe business failure code, or a technical
exception type.

Raw exception messages and tool payloads are deliberately excluded. Failed or
cancelled attempts are still represented even when no complete continuation
cycle can be published.

## Diagnostic summary

The final summary contains:

- provider-turn count;
- attempted tool-execution count;
- cumulative provider time;
- cumulative tool time;
- overall latency;
- termination reason;
- safe error-code summary;
- cleanup completion status.

Durations use a monotonic clock. UTC timestamps exist for human correlation and
timeline display, not elapsed-time calculation.

## Structured logging

Each observability event includes the same fields:

```text
event
trace_id
conversation_id
provider
model
provider_turn
tool_call_id
detail
```

Unavailable fields are explicitly logged as `None`, keeping the log shape
stable. Event details are controlled labels only and never contain customer or
provider payload data.

## Publication and future integration

The service accepts an injected trace sink:

```python
BoundedModelToolLoopService(..., trace_sink=publish_trace)
```

The default sink writes a safe structured summary. A future telemetry exporter,
evaluation runner, or dashboard ingestion service can consume immutable traces
without changing orchestration. No such integrations are implemented in this
stage.

## Concurrency

Recorder state is local to one invocation. Concurrent calls through the same
service instance publish separate immutable traces with distinct trace IDs,
conversation IDs, provider turns, tools, timelines, and diagnostics. Tests verify
that concurrent traces do not exchange events or tool-call identities.
