# Order Cancellation

## Scope

`cancel_order` is the first concrete Stage 12 write operation. It changes only
an owned order's status and `updated_at` timestamp. It is not registered with a
provider or exposed over HTTP in this milestone.

## Lifecycle

```text
Stage 11 security gates
  -> WriteExecutionContext
  -> CancelOrderInput validation
  -> ownership and eligibility validation (read only)
  -> WriteFrameworkExecutor
  -> SQLAlchemyTransactionManager
  -> SELECT ... FOR UPDATE
  -> locked eligibility recheck
  -> set status and updated_at
  -> automatic commit / rollback
  -> WriteResult
  -> WriteAuditEvent
```

The operation never calls `commit()`, `rollback()`, or `flush()`. The shared
transaction manager owns the session transaction and cleanup.

## Business rules

The single `OrderCancellationPolicy` owns all eligibility decisions.

| Current status | Result |
| --- | --- |
| `pending` | Cancellation allowed |
| `confirmed` | Cancellation allowed |
| `preparing` | Cancellation allowed |
| `dispatched` | `order_cancellation_not_allowed` |
| `delayed` | `order_cancellation_not_allowed` |
| `delivered` | `order_cancellation_not_allowed` |
| `cancelled` | `order_already_cancelled` |

Missing and unowned orders intentionally return the same safe
`order_not_found` result to prevent resource enumeration.

## Validation and concurrency

The customer-facing order number is normalized and validated before execution.
Trusted customer identity comes only from `WriteExecutionContext`. A read-only
preflight evaluates ownership and status before a transaction is opened.

Inside the transaction, the persistence adapter locks the selected row and the
same centralized policy evaluates the current state again. This is not a second
business-rule implementation; it closes the time-of-check/time-of-use window.
A concurrent state change causes automatic rollback and never overwrites the
newer state.

## Idempotency

The first eligible request changes the order to `cancelled`. Every later request
observes the terminal state, opens no transaction, changes no timestamps, and
returns the same `order_already_cancelled` result and public message.

## Persistence boundary

The business operation depends on the `OrderCancellationReader` and
`OrderCancellationStore` protocols. The SQLAlchemy adapters are replaceable and
keep ORM details outside the rules. The reader reuses `OrderRepository`; the
store performs only the locked write required by this operation.

No new table, column, relationship, or migration is required because `orders`
already supports the `cancelled` state and `updated_at` timestamp.

## Audit behavior

The shared executor emits a safe event containing operation/version, timestamp,
request and correlation identifiers, the customer-safe order number, outcome,
and safe failure code. Authenticated actor traceability remains linked through
the existing Stage 11 request/correlation audit chain; raw customer identity is
not duplicated in the write event.

## Extension points

- Add allowed states only in `CANCELLABLE_ORDER_STATUSES`.
- Add or refine decisions only in `OrderCancellationPolicy`.
- Replace persistence by implementing the reader/store protocols.
- Add transport or model exposure later without changing business rules.
- Add cancellation-reason metadata only through a reviewed schema milestone.
