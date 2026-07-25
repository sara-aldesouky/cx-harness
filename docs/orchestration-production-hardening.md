# Stage 9.5 — Orchestration Production Hardening

Stage 9.5 adds defensive runtime boundaries around the existing bounded loop.
It does not change the provider-neutral contracts, execute tools in parallel,
or add business capabilities.

## Failure boundaries

Provider output is accepted only when it forms a valid normalized turn. The
Ollama adapter rejects missing messages, invalid JSON, empty final content,
malformed tool-call objects, absent names or IDs, and non-object arguments.
Malformed calls never reach tool resolution or execution. Transport, timeout,
and malformed-response failures produce structured termination metadata without
including raw payloads in customer messages or logs.

Tool calls are checked twice: the existing resolver validates registration,
enablement, version, and Pydantic arguments; the loop additionally enforces
configured count and payload boundaries. Only registered tools can execute.
Trusted customer identity continues to come exclusively from
`ExecutionContext`, never model arguments.

## Loop protection

The existing maximum-turn boundary remains authoritative. Repeated call IDs are
rejected, and a canonical fingerprint of tool name, version, and normalized
arguments detects an equivalent request even when the provider regenerates its
call ID. Repeating the same tool with different arguments remains valid.

Every loop-limit or repetition termination includes a deterministic internal
code and a safe customer-facing final response. The execution trace records the
termination and cleanup events.

## Configurable limits

| Setting | Default | Purpose |
|---|---:|---|
| `MAX_USER_MESSAGE_CHARS` | 16,384 | Maximum characters in one user message |
| `MAX_CONVERSATION_HISTORY` | 100 | Maximum prior messages |
| `MAX_PROVIDER_MESSAGES` | 128 | Maximum normalized messages sent to a provider |
| `MAX_MODEL_TURNS` | 5 | Maximum sequential provider turns |
| `MAX_TOOLS_EXPOSED` | 64 | Maximum tools registered in one runtime |
| `MAX_TOOL_CALLS_PER_TURN` | 16 | Maximum calls returned in one turn |
| `MAX_TOOL_ARGUMENT_BYTES` | 16,384 | Maximum compact JSON argument size per call |
| `MAX_TOOL_RESULT_BYTES` | 65,536 | Maximum normalized execution outcome size |
| `MAX_PROVIDER_RESPONSE_BYTES` | 1,048,576 | Maximum raw and normalized provider response size |

All values have positive, finite upper bounds and are validated when settings
load. Zero, negative, or unsafe unlimited values fail fast. Ollama remains
restricted to localhost; its endpoint, model name, connect timeout, and read
timeout are also validated before runtime construction.

## Graceful shutdown

The FastAPI lifespan opens a thread-safe admission gate. Shutdown closes
admission, cooperatively cancels tracked invocations, clears the cached mapper,
closes provider HTTP clients after each application invocation, and disposes the
cached SQLAlchemy engine. Run-local state and trace recorders still clean up in
their existing `finally` paths for success, failure, timeout, and cancellation.

Because the current orchestration contract is synchronous, cancellation is
cooperative at provider/tool boundaries; configured network and tool timeouts
remain required for bounded termination of blocking I/O.

## Security and concurrency guarantees

- Grounding policy cannot be disabled by user instructions.
- System instructions explicitly treat tool output as untrusted data.
- Oversized values are rejected without logging their payloads.
- Customer-facing errors contain stable public text, not raw exceptions.
- Trace logging contains correlation metadata but not prompts, arguments,
  results, credentials, or customer data.
- Mutable messages, fingerprints, tool cycles, state, and trace data are scoped
  to one invocation. Concurrent success, timeout, cancellation, and failure
  paths cannot share or corrupt orchestration state.

## Verification

Run the focused hardening suite, then the complete backend suite:

```bash
cd backend
.venv/bin/python -m pytest tests/services/test_orchestration_hardening.py \
  tests/services/test_orchestration_resilience.py \
  tests/services/test_orchestration_observability.py \
  tests/providers/test_ollama_tool_loop.py
.venv/bin/python -m pytest
```

The automated suite uses mocked transports and isolated fakes unless a test is
explicitly marked as live integration. Stage 9.5 does not require or access the
Render database.
