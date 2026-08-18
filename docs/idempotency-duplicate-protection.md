# Stage 12.7 — Idempotency and Duplicate Protection

## Purpose

Stage 12 writes are safe when a client retries after a timeout, loses a
response, refreshes a browser, reconnects a mobile client, or submits the same
operation concurrently. Idempotency is enforced by business state, normalized
request identity, row locking, database constraints, and the shared write
framework. It does not depend on a model provider or orchestration behavior.

## Framework lifecycle

Every attempt retains the existing lifecycle:

```text
Validation
  -> Transaction
  -> Locked business-state recheck
  -> Business logic
  -> Output validation
  -> Commit
  -> Audit
  -> Return
```

Validation can reject an already-completed operation before a transaction.
When two requests pass preflight simultaneously, the transaction-side locked
recheck prevents the second request from repeating the change.

## Operation guarantees

| Operation | Logical identity | Duplicate protection | Retry result |
|---|---|---|---|
| Order cancellation | Customer-owned order number | Order row lock and terminal `cancelled` state | `order_already_cancelled`; the original timestamp is unchanged |
| Delivery address update | Customer-owned order number plus normalized address | Order row lock and normalized value comparison | `address_already_up_to_date`; no timestamp update |
| Refund initiation | Customer-owned order/payment state | Order row lock and existing refund lookup | Existing refund is retained; no second refund or event |
| Support ticket creation | Customer plus normalized issue fingerprint | Customer/order locks and partial unique active-issue index | Existing active ticket reference is retained |

Inputs are normalized before identity comparisons. Order numbers use their
normalized uppercase form, addresses use normalized whitespace, and support
issues use a SHA-256 fingerprint over normalized non-sensitive fields.

## Database protection

- Order cancellation and delivery address updates serialize on the order row.
- Refund initiation also serializes on the order row. A global unique payment
  constraint is intentionally not used because the normalized refund model
  permits legitimate future refund history; the locked business rule prevents
  duplicate initiation.
- Support-ticket creation serializes on the customer and related order. The
  partial unique index on `(customer_id, issue_fingerprint)` independently
  prevents two active duplicates while allowing a future ticket after an old
  one is resolved or closed.
- The ticket reference has a separate unique index.
- All constraint errors roll back through `TransactionManager`; partial parent
  or child records cannot commit.

## Request identity and retries

`WriteExecutionContext.request_id` already supplies trusted request identity.
It can be populated from a future HTTP `Idempotency-Key` without changing any
business operation. Current clients are not required to provide such a key:
business-state idempotency provides correctness even when retries receive new
request IDs.

A distributed idempotency-result store is deliberately deferred until an API
contract requires exact response replay. Such a store could atomically map a
trusted idempotency key to an operation, principal, normalized request digest,
and completed result. It would improve response replay but is not required to
prevent duplicate business actions.

## Audit semantics

Every received attempt may produce an audit event so operational retry traffic
remains traceable. It must not look like repeated successful business changes.
`WriteAuditEvent.business_change_applied` distinguishes:

- `true`: this attempt applied the business transition;
- `false`: this successful attempt returned an existing idempotent result;
- `null`: the attempt failed or was rejected before a business change.

Each retry storm therefore contains exactly one `business_change_applied=true`
event for a given change. Request and correlation identifiers remain available
for downstream sink deduplication and request-chain analysis without storing
customer PII.

## Concurrency verification

PostgreSQL integration tests synchronize requests after preflight so they race
for the actual database locks. The suite covers five concurrent cancellations,
five identical address updates, five refund initiations, and ten support-ticket
requests. It verifies one business mutation, stable final state, one refund
event, one active ticket, bounded completion, and accurate audit classification.

## Extension guidance

A future write operation should:

1. Define its normalized logical request identity.
2. Reject completed work during preflight when possible.
3. Lock the smallest stable parent resource in a documented order.
4. Re-evaluate duplicate and eligibility rules under that lock.
5. Add an appropriate database uniqueness constraint when uniqueness is an
   invariant of the data model.
6. Return an existing logical result rather than performing a second mutation.
7. Override `business_change_applied()` when a successful output can represent
   an idempotent no-op.

Business operations must never manage commits, rollbacks, retries, audit sinks,
or provider behavior.
