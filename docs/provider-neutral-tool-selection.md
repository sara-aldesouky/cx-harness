# Provider-Neutral Tool Selection

Stage 8.2 defines how a model-originated tool request enters the harness without
coupling that request to a provider format or executing the selected tool.

```text
Provider adapter (future)
        |
        v
ToolSelectionRequest
        |
        v
ToolSelectionResolver --> ToolRegistry
        |
        v
ValidatedToolSelection
```

`ToolSelectionRequest` contains a caller-supplied correlation ID, tool name,
optional semantic version, and structured JSON arguments. The caller owns call
ID uniqueness; the contract normalizes and validates that the identifier is
non-empty.

The resolver delegates discovery and version safety to `ToolRegistry`. It
rejects disabled tools and validates arguments through the selected tool's
declared Pydantic input schema. Consequently, normalization and domain rules
remain owned by the tool input contract rather than being duplicated in the
resolver.

`ValidatedToolSelection` contains the resolved name and version plus normalized
JSON arguments. Both contracts recursively copy and freeze their structured
arguments while serializing them as ordinary JSON objects and arrays.

This boundary does not instantiate a tool, call `execute()`, create prompts,
parse provider payloads, access a database, or persist execution state.
