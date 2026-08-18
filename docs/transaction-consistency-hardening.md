# Transaction and Consistency Hardening

## Framework ownership

Every Stage 12 write uses the same lifecycle:

```text
Security proof
  -> contract checks
  -> pre-transaction business validation
  -> transaction begin
  -> locked state reload
  -> business mutation
  -> output contract validation
  -> commit or rollback
  -> best-effort audit
  -> standardized WriteResult
```

`WriteFrameworkExecutor` owns orchestration and safe failure mapping.
`SQLAlchemyTransactionManager` owns transaction opening, commit, rollback,
session cleanup, and translation of database failures. Static contract tests
verify that no concrete operation invokes `begin`, `commit`, `rollback`, or
`flush`.

## Transaction guarantees

- A callback is invoked exactly once inside one transaction.
- Successful output validation is required before commit.
- Exceptions during locking, mutation, output validation, flush, or commit roll
  back the entire transaction.
- Repository/preflight failures occur before transaction entry and now return a
  standardized infrastructure failure.
- Business validation rejection opens no transaction.
- The framework performs no automatic retry, preventing duplicate side effects.
- SQLAlchemy context managers close transaction resources on every path.

## Rollback verification

Database-backed fault injection raises immediately after each operation mutates
its ORM state. Verification from a separate session proves:

- cancelled order status remains unchanged;
- delivery address remains unchanged;
- neither Refund nor its related RefundEvent survives;
- no SupportTicket survives;
- constraint failures leave the previously committed record intact and create
  no partial second record.

Invalid operation outputs are validated inside the transaction callback, so
they roll back before commit. Validation-reader, timeout, unavailable-database,
serialization-conflict, and unexpected manager failures produce safe
`WriteResult` failures without exposing exception details.

## Concurrency strategy

All operations acquire stable PostgreSQL row locks before mutation:

- cancellation and address changes lock the order;
- refund initiation locks the order before duplicate lookup and creation;
- support-ticket creation locks the customer and then the optional order.

Lock ordering is consistent. Ticket creation is the only operation requiring
two business locks and always acquires customer before order; other operations
never acquire customer after order, avoiding a lock cycle.

Concurrent tests synchronize both requests after preflight and verify:

- two cancellations produce exactly one state change;
- identical address changes produce one update and one no-change result;
- two refund requests create exactly one Refund and one RefundEvent;
- two ticket requests create exactly one active SupportTicket;
- mixed cancellation/address execution completes without deadlock and leaves a
  valid terminal order state.

The partial unique active-ticket index is an additional database invariant.
Refund and ticket duplicates are primarily serialized through their parent-row
locks, allowing deterministic idempotent outcomes instead of constraint errors.

## Consistency guarantees

- Foreign keys connect all created records to existing trusted parents.
- Refund request and requested event are committed or rolled back together.
- Optional ticket-order deletion uses `SET NULL`; customer deletion is
  restricted while a support record exists.
- Operation timestamps are generated once and reused across their related
  records and results.
- Repeated requests either return the existing logical result or a stable
  already-completed business response.
- No operation modifies data outside its documented aggregate.

## Audit isolation

Audit emission occurs only after validation rejection or transaction completion.
It is outside the business transaction by design. A failing audit observer:

- cannot roll back a committed customer change;
- cannot transform a successful result into failure;
- cannot expose payloads because events contain only safe references and codes.

The Stage 11 audit subsystem remains responsible for resilient sink delivery and
failure observation.

## Transaction scope and performance

Preflight reads and input normalization stay outside the transaction. Inside the
transaction each operation performs only its locked reload, minimal consistency
queries, mutation, and output construction. External providers, audit sinks,
network calls, and customer-facing formatting are excluded from lock scope.

PostgreSQL concurrency tests use bounded completion timeouts to detect deadlocks.
No deadlock or orphaned state was observed.

## Extension guidance

Future write operations must:

1. Implement immutable input/output contracts and `BaseWriteOperation`.
2. Keep reusable business rules in one policy component.
3. Complete ordinary validation before transaction entry.
4. Lock the aggregate root in a globally consistent order.
5. Re-evaluate mutable rules under the lock.
6. Make all related writes in the supplied transaction.
7. Return the declared output type before commit.
8. Never manage sessions or transactions directly.
9. Emit only customer-safe audit references.
10. Prove rollback and concurrent idempotency with real PostgreSQL tests.
