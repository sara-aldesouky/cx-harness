# Tool Execution Request Boundary

Stage 8.6 defines the immutable command that may later cross into tool
execution. It does not execute anything.

```text
Provider output                     untrusted
      |
ToolSelectionRequest                parsed, still untrusted
      |
ValidatedToolSelection              tool-schema validated
      |                                      +
      |                              ExecutionContext
      |                              trusted application data
      +------------------------------+
                     |
                     v
          ToolExecutionRequestFactory
                     |
                     v
             ToolExecutionRequest           execution-ready
```

## Trusted context

The project already had a frozen `ExecutionContext`, so Stage 8.6 reuses it
rather than creating a competing identity contract. It contains UUID trace and
execution identifiers plus optional conversation, model-run, and customer
identity and normalized model/experiment/use-case labels.

Trusted context must come from authentication, the backend, harness runtime, or
experiment runner. Model-generated order IDs, tool arguments, provider payloads,
secrets, permissions, and arbitrary dictionaries do not belong in it.

## Factory boundary

`ToolExecutionRequestFactory.create()` accepts only a
`ValidatedToolSelection` and an `ExecutionContext`. It preserves canonical tool
identity, resolved version, call ID, normalized arguments, and trusted context.
Arguments are recursively copied and frozen, and context is defensively copied.

The factory does not query a registry, re-run a tool input schema, instantiate a
tool, check authorization, access repositories, persist data, or execute a
capability. A future executor should accept `ToolExecutionRequest` as its input
boundary rather than accepting raw provider output.
