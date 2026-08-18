# Delivery Address Update

## Scope

`update_delivery_address` changes the delivery address on one eligible order.
It uses the Stage 12.1 framework and existing Stage 11 security evidence. This
milestone does not expose the operation through a provider or HTTP endpoint.

No schema change is required: the existing `orders.delivery_address` and
`orders.updated_at` fields are the authoritative data.

## Lifecycle

```text
Stage 11 security gates
  -> immutable WriteExecutionContext
  -> strict UpdateDeliveryAddressInput
  -> preflight ownership / state / idempotency policy
  -> WriteFrameworkExecutor
  -> SQLAlchemyTransactionManager
  -> lock order row
  -> re-evaluate the same policy
  -> update address and updated_at
  -> automatic commit or rollback
  -> standardized WriteResult
  -> address-free WriteAuditEvent
```

The business operation contains no `commit()`, `rollback()`, or `flush()`.

## Business rules

`AddressUpdatePolicy` is the single source of eligibility decisions.

| Current status | Result |
| --- | --- |
| `pending` | Update allowed |
| `confirmed` | Update allowed |
| `preparing` | Update allowed |
| `dispatched` | Update rejected |
| `delayed` | Update rejected |
| `delivered` | Update rejected |
| `cancelled` | Update rejected |

Missing and unowned orders return the same `order_not_found` result. This
preserves the existing resource-enumeration protection.

## Address validation

- Leading, trailing, and repeated whitespace is normalized.
- The normalized address must not be empty.
- Maximum normalized length is 500 characters.
- Unicode letters and numbers are supported.
- Common address punctuation is supported: spaces, period, comma, apostrophe,
  hash, hyphen, slash, and parentheses.
- Control characters, emoji, and unrelated symbols are rejected.
- At least one letter or number is required.

Validation happens before opening a transaction. The full address is never
included in the operation's output or audit event.

## Transaction and concurrency strategy

The persistence adapter executes `SELECT ... FOR UPDATE`. The centralized
policy is evaluated again against locked current state, closing the gap between
preflight and mutation. Concurrent requests therefore serialize on the order:

- an intervening terminal status causes safe rollback;
- an identical update observes the current value and performs no second write;
- eligible different updates execute serially rather than concurrently.

The shared transaction manager commits only after output-contract validation.
All unexpected failures roll back automatically.

## Idempotency

When preflight finds the requested normalized address already stored, the
operation opens no transaction and returns `address_already_up_to_date`. If an
identical concurrent request completes after preflight but before the lock is
acquired, the locked recheck returns a successful no-change outcome. Neither
path changes the address or timestamp again.

## Audit and privacy

The shared event records the operation, version, timestamp, request and
correlation IDs, safe order reference, outcome, and safe failure code. It does
not contain the old or new address. Authenticated actor linkage continues
through the existing Stage 11 correlation chain without duplicating raw PII.

## Extension points

- Change eligible states only through `ADDRESS_UPDATE_ELIGIBLE_STATUSES`.
- Extend domain decisions only through `AddressUpdatePolicy`.
- Adjust approved address syntax centrally in `normalize_delivery_address`.
- Replace persistence through the reader and store protocols.
- Add structured address fields only in a separately reviewed schema milestone.
