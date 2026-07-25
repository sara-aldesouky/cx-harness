# Provider Tool-Call Translation

Stage 8.3 introduces the boundary where a provider-specific response becomes a
provider-neutral `ToolSelectionRequest`.

```text
Provider output
      |
      v
ProviderToolCallAdapter
      |
      v
tuple[ToolSelectionRequest, ...]
      |
      v
ToolSelectionResolver (separate stage and responsibility)
```

`ProviderToolCallAdapter` is an abstract translation contract. Each future
provider adapter owns only its provider's response shape. The interface returns
an ordered immutable tuple and does not depend on discovery, execution,
persistence, prompts, HTTP, or database infrastructure.

`MockProviderToolCallAdapter` accepts the deterministic test-only shape:

```json
{
  "tool_calls": [
    {
      "id": "call-001",
      "name": "ping",
      "version": "1.0.0",
      "arguments": {"message": "hello"}
    }
  ]
}
```

The mock format is not a universal model API. The adapter checks only structural
integrity and duplicate call IDs. Tool existence, enablement, version
resolution, and business-argument validation remain exclusively owned by
`ToolSelectionResolver`.

Malformed payload details are retained only as exception causes. Public adapter
errors expose stable messages without echoing raw provider payloads or Pydantic
validation internals.
