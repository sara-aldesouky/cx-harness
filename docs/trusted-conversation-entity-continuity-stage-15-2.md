# Stage 15.2 — Trusted Conversation Entity Continuity

## Problem

Customer-facing data protection masks order references before assistant text is
stored in public conversation history. That history is intentionally unsafe as
an identity source. Reconstructing an order identity from masked text caused
later tool selections to fail validation.

## Trust boundary

Trusted continuity is held outside customer messages, provider messages, and
provider arguments. It is populated only after a typed tool result completes
successfully. Provider text cannot create or update trusted state.

The runtime order is:

1. provider tool selection;
2. trusted reference resolution;
3. the existing customer-scoped `OrderEntityResolver` re-verifies the entity;
4. protected write selections enter the frozen `TrustedArgumentBinder`, which
   binds the repository-verified public order reference and discards the
   provider value; legacy read selections repair only masked/missing order
   arguments from the same customer-scoped resolver before ordinary binding;
5. schema validation;
6. role, tool, and ownership authorization;
7. business execution;
8. successful typed result capture;
9. provider/public redaction.

Continuity is context, not authorization. Authorization still executes after
binding and schema validation.

## State model

`TrustedConversationEntityState` is immutable and partitioned by both trusted
conversation UUID and trusted customer UUID. It contains a selected entity and
an ordered candidate tuple. References record entity type, optional internal
identity, public reference, source tool, source turn, verification timestamp,
and verification status. The current implementation populates only order
public references; optional internal identity remains reserved for future
trusted adapters and is never exposed to the provider.

The in-memory store uses a lock, defensive Pydantic copies, and monotonic
revision updates. It is process-local by design; no schema migration is needed.

## Candidate lists and references

Successful collection results retain their verified order sequence. English,
Egyptian Arabic, Franco-Arabic, and mixed references can select candidates:

- `the first one`, `الأول`, `awel wa7ed`;
- `the second one`, `التاني`, `el tany`;
- `the last order`, `آخر أوردر`, `akher order`;
- `that order`, `الأوردر ده`, `el order da` after a selection exists.

Ambiguous, unavailable, stale, or out-of-range references fail closed and ask
for clarification. Masked identifiers are never accepted as verified values.

## Lifecycle

- Create after a successful trusted tool result containing order identity.
- Preserve list ordering for candidate selection.
- Replace the selected entity after successful direct lookup or explicit
  candidate selection.
- Reject customer or conversation partition mismatches.
- Expire by configurable wall-clock TTL or turn gap.
- Ignore failed tool results.
- Delete explicitly when the conversation is cleaned up.

## Observability and privacy

`ContinuityAuditMetadata` contains only whether state was consulted/reused,
entity category, source tool/turn, resolution method, and failure category. It
contains no UUID, order number, provider argument, address, or customer text.
No logging sink is introduced by this stage.

## Limitations

The default store is process-local and does not survive restarts. Distributed
continuity requires a future implementation of the same partition and revision
semantics. Stage 15.2 intentionally implements only order continuity and does
not create a generic conversation-memory system.
