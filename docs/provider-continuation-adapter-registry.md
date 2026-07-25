# Provider Continuation Adapter Registry

Stage 8.10 adds explicit, in-memory discovery for provider continuation
translation adapters.

```text
Provider identity
       |
       v
ProviderContinuationAdapterRegistry
       |
       v
ProviderContinuationAdapter
       |
       v
Future continuation translation
```

Continuation adapters need their own registry because translating completed tool
outcomes back into a provider continuation format is a different boundary from
parsing provider tool-call requests. Keeping it separate from
`ProviderToolCallAdapterRegistry` prevents input translation and continuation
translation from becoming coupled.

Provider identities follow the established convention: require a string, remove
surrounding whitespace, lowercase it, and reject a blank result. Registration is
explicit and instance-scoped, so dependencies can be assembled without global
mutable state. The registry stores the exact supplied adapter instances.

`list_providers()` and `items()` return immutable tuple snapshots in normalized,
alphabetical order. The registry only performs discovery: it never calls
`translate()`, accepts outcomes, invokes providers or models, executes tools,
accesses persistence, or constructs continuation payloads.

Runtime wiring is deliberately deferred. A later orchestration stage can receive
this registry through dependency injection after continuation behavior and its
ownership boundaries are explicitly designed.
