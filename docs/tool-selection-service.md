# Tool Selection Service

Stage 8.5 composes provider adapter discovery, provider-output translation, and
tool selection validation behind one provider-neutral application boundary.

```text
provider_name + provider_output
              |
              v
ToolSelectionService
              |
              +--> ProviderToolCallAdapterRegistry.get()
              |              |
              |              v
              |    ProviderToolCallAdapter.translate()
              |              |
              |              v
              |    tuple[ToolSelectionRequest, ...]
              |              |
              +--------------+
                             v
                  ToolSelectionResolver.resolve()
                             |
                             v
              tuple[ValidatedToolSelection, ...]
```

The service receives both dependencies through constructor injection. It
preserves call ordering and returns an immutable tuple. A valid no-call provider
response returns `()`.

Resolution is fail-fast. If call N fails, later calls are not processed and no
partial tuple is returned. Service exceptions distinguish adapter lookup,
translation, and selection resolution while chaining the original domain error.
Messages may include provider identity, call index, and call ID, but never echo
provider payloads or argument values.

This is a validation boundary, not an execution engine. It does not instantiate
tools, call `BaseTool.execute()`, persist records, access a database, call a model
provider, generate prompts, or participate in a continuation loop.
