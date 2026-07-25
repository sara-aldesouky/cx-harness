# Provider-Neutral Continuation Translation Service

Stage 8.11 adds a narrow orchestration boundary around continuation-adapter
discovery and translation.

```text
provider name + ToolExecutionOutcome
                 |
                 v
ProviderContinuationService
                 |
                 v
ProviderContinuationAdapterRegistry
                 |
                 v
ProviderContinuationAdapter.translate(outcome)
                 |
                 v
ProviderContinuationPayload
```

Adapters own provider-specific translation. The service owns orchestration: it
resolves the correct adapter, invokes it exactly once, and verifies the returned
contract. Keeping these responsibilities separate prevents adapters from taking
on discovery concerns and lets callers use one stable provider-neutral boundary.

The adapter registry remains the source of truth for provider-name validation and
lookup. The service uses the same normalized identity only for safe consistency
checks and error context; it adds no aliases or fallback provider.

Each call accepts exactly one outcome. Batch behavior, partial success, ordering
across multiple outcomes, and model continuation loops require separate policies
and are deliberately deferred.

The service rejects non-contract results, provider mismatches, and call-ID
mismatches. It never repairs defective adapter output because either mismatch
could break tool-call correlation. Valid payloads are returned as the exact
immutable instance supplied by the adapter, without copies or wrappers.

Model invocation remains deferred. This service does not add conversation
messages, generate prompts, invoke a provider, persist payloads, or wire itself
into the runtime pipeline.
