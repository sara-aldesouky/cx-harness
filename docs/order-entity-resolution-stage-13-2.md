# Stage 13.2 — Deterministic Order Entity Resolution

Stage 13.2 introduces a provider-independent resolver for the `ORDER` entity.
It does not bind tool arguments, execute tools, mutate conversation state, or
integrate with the model loop.

## Resolution boundary

`EntityResolutionRequest` carries a trusted customer UUID, conversation UUID,
the current customer-authored message, optional Stage 13.1 state, and explicit
resolution requirements. Provider output is not an input to this contract.

`OrderMentionExtractor` recognizes only complete public references matching
`ORD-` followed by five digits. Matching is case-insensitive, results normalize
to uppercase, arbitrary numbers are ignored, and malformed references are never
repaired or guessed. Message spans and correction provenance are preserved.

## Priority

The resolver applies this deterministic order:

1. Explicit public references in the current customer message.
2. Explicit customer corrections, represented on the explicit mention.
3. A selected, repository-verified order reference in conversation state.
4. A focused, repository-verified order reference in conversation state.
5. Exactly one active customer order, when permitted.
6. The latest customer order, only when explicitly permitted.
7. A safe not-found or clarification result.

Multiple candidates are sorted by `created_at` descending and then
`order_number` descending. The resolver never relies on implicit database
ordering and never selects arbitrarily.

## Repository and identity safety

`OrderResolutionRepository` is a narrow structural interface returning only
`OrderResolutionRecord(order_number, created_at)`. It exposes no ORM object,
session, internal order UUID, or customer UUID.

`ExistingOrderRepositoryAdapter` reuses the established `OrderRepository` and
enforces customer-scoped lookup before mapping an order to the minimal record.
Cross-customer and nonexistent references both return the same safe result.

Every lookup receives `trusted_customer_id` from the caller. Conversation state
is a reference source, not authorization: state references are reverified
through the customer-scoped repository boundary before resolution succeeds.

## State behavior

The resolver reads immutable Stage 13.1 snapshots but never saves or modifies
them. Only order references sourced from a verified tool result or repository
lookup can satisfy implicit resolution. Expired, invalid, unverified, or stale
references fail safely. Explicit customer corrections override existing focus
and are marked in the result so a future state reducer can update focus and
clear incompatible pending operations.

## Future integration

A later stage may consume `ResolvedEntity` for trusted server-side argument
binding. Stage 13.2 deliberately does not implement that binder, write
preconditions, runtime integration, tool execution, provider changes, or entity
resolution for refunds, tickets, addresses, or other domains.
