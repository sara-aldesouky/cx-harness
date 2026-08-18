# Stage 13.1 — Conversation State Foundation

Stage 13.1 introduces provider-independent, immutable conversation-state
contracts and storage infrastructure. It does not resolve entities, bind tool
arguments, integrate with the runtime, or execute business operations.

## Contracts

`ConversationState` is a versioned JSON snapshot containing lifecycle metadata,
trusted entity references, deterministic conversational focus, an optional
pending-operation summary, and a summary of the last verified tool outcome.
It contains no ORM objects, database sessions, repositories, providers, tools,
or security decisions.

All nested Pydantic models are frozen and reject extra fields. Timestamps must
be timezone-aware and are normalized to UTC. Schema version `1.0` is explicit;
unknown versions fail validation rather than being interpreted optimistically.

Entity references record provenance using one of four trusted categories:
execution context, verified tool result, repository lookup, or explicit customer
input. Stage 13.1 records this provenance but does not interpret or resolve it.

## Storage boundary

`ConversationStateStore` defines five operations:

- `load(conversation_id)`
- `save(state)` for revision-zero creation
- `compare_and_swap(conversation_id, expected_revision, state)`
- `delete(conversation_id)`
- `expire(conversation_id)`

`InMemoryConversationStateStore` is intended for unit tests and local
development. Each instance owns its own dictionary and lock; there is no global
mutable registry. A future distributed store can implement the same abstraction
without changing state contracts or lifecycle callers.

## Revision model

Initial state is revision zero. Every successful service save creates exactly
the next revision and uses atomic compare-and-swap. Concurrent writers holding
the same snapshot cannot both succeed: one stores the next revision and the
other receives `ConversationStateConflictError`.

Stored and returned snapshots are deep copies. Callers cannot use object
identity or nested mutable references to change stored state.

## Lifecycle and expiration

`ConversationStateService` creates, loads, revises, expires, and deletes state.
It owns the configured TTL and revision increment but knows nothing about tools,
providers, repositories, database models, business logic, or security.

Creation sets `ACTIVE`, revision zero, UTC lifecycle timestamps, and an expiry
based on the configured TTL. A successful save refreshes the TTL. Explicit
expiration marks a new revision `EXPIRED`. Lazy TTL detection removes an expired
snapshot and raises `ConversationStateExpiredError` on the observing load; a
subsequent load reports the state as missing.

## Future integration points

Later stages may add, without changing this stage's responsibilities:

- A deterministic entity resolver consuming entity references.
- A trusted argument binder operating before tool-schema validation.
- A distributed Redis-backed implementation with atomic CAS and TTL.
- Runtime state loading and verified-result reduction.
- Write-precondition evaluation.

Those components are intentionally absent from Stage 13.1. The existing model
loop, provider behavior, tool execution, repositories, security gates, and
business operations remain unchanged.
