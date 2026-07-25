# Stage 9.3 — Orchestration Resilience and Recovery

Stage 9.3 strengthens the existing synchronous, provider-independent bounded
model/tool loop. It does not change the Stage 8 or Stage 9 request, response,
selection, execution, outcome, or continuation contracts.

## Run-local state

Every invocation creates a private `OrchestrationExecutionState` keyed by the
trusted `ExecutionContext.trace_id`. The state moves through these phases:

```text
ready → provider_running → ready → tool_running → ready
  └──────────────────────────────→ terminated → cleaned
```

Provider turns must be sequential. A tool call ID is claimed before resolution
or execution and cannot be claimed twice. Completed call IDs are recorded only
after a complete continuation cycle exists. Invalid phase transitions fail
immediately as internal orchestration errors.

The state object is created inside `run()` and cleaned in `finally`. It is never
stored globally or reused by another conversation.

## Failure and recovery paths

| Condition | Termination | Safe behavior |
|---|---|---|
| Provider timeout | `timeout / provider_timeout` | No provider output is processed. |
| Tool timeout | `timeout / tool_timeout` | Audit is finalized as an error; no continuation is sent. |
| Provider cancellation | `cancelled / provider_cancelled` | The turn is discarded at a safe boundary. |
| Tool cancellation | `cancelled / tool_cancelled` | Audit is finalized; no partial cycle is published. |
| Provider failure | `provider_error` | Completed earlier cycles remain visible; temporary state is cleaned. |
| Technical tool failure | `tool_error` | A safe customer message is returned. |
| Business tool failure | `tool_business_failure` | The tool's safe public failure is returned. |
| Duplicate call ID | `invalid_tool_call / duplicate_tool_call` | The duplicate is never resolved or executed. |
| Overall deadline | `timeout / loop_timeout` | The next provider turn is not started. |

A later application invocation always receives a new execution state. Recovery
therefore means starting a clean bounded run; the loop never retries or resumes
an uncertain tool execution automatically. This prevents duplicate business
operations after failures.

## Cancellation and timeout semantics

`OrchestrationCancellationToken` is a thread-safe cooperative signal. The loop
checks it before provider work and after every provider and tool boundary.
Provider or tool implementations may also raise their standard cancellation or
timeout exceptions. Those signals retain their meaning through the existing
tool-cycle layers.

The current provider and tool contracts are synchronous. Stage 9.3 does not
create background workers or attempt to kill Python code mid-instruction.
Network providers must keep their transport timeouts configured, and long-running
tools must use bounded I/O or raise `TimeoutError`. This preserves deterministic
cleanup without introducing hidden parallel execution.

## Audit and partial turns

`ToolExecutor` finalizes its audit record for normal results, expected business
failures, timeouts, cancellation exceptions, and interruptions. A tool cycle is
added to the loop result only after execution, outcome correlation, and provider
continuation translation all complete.

If the second tool in a turn fails, the first completed cycle remains in the
structured result, the second audit is finalized, and the provider is not called
again. No incomplete continuation payload enters the next turn.

## Correlation

The trusted `trace_id` is preserved when a per-tool `execution_id` is generated.
The same trace ID appears in:

- loop start and provider-turn events;
- tool start and terminal events;
- completed tool-cycle events;
- loop termination events;
- state-cleanup events.

The per-tool execution ID still identifies one exact audited tool attempt.

## Concurrency

All mutable orchestration collections and state belong to one `run()` call.
Provider and registry dependencies remain injected and reusable, while working
messages, claimed call IDs, completed cycles, pending results, and cancellation
state are never shared between conversations. Tests exercise simultaneous
conversations against one service instance and verify distinct traces, call IDs,
results, and cleaned state objects.
