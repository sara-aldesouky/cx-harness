# Provider Tool-Call Adapter Registry

Stage 8.4 adds explicit, in-memory discovery for provider tool-call translation
adapters.

```text
Provider identity
       |
       v
ProviderToolCallAdapterRegistry
       |
       v
ProviderToolCallAdapter
       |
       v
tuple[ToolSelectionRequest, ...]
```

The registry stores adapter instances because this matches the project's
dependency-injection conventions and allows future adapters to receive their own
configuration explicitly. Registrations belong to each registry instance; no
global mutable registry or automatic registration is introduced.

Provider identities are stripped and lowercased, matching existing provider and
prompt-adapter registries. Aliases are not created. Discovery returns immutable,
alphabetically ordered tuple snapshots through `list_providers()` and `items()`.

The registry maps identity to adapter only. It does not call adapters, parse
provider output, access `ToolRegistry`, validate business arguments, instantiate
tools, execute capabilities, access persistence, or generate prompts.
