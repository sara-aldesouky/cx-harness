# Refund Initiation

## Scope

`initiate_refund` creates a customer refund request using the existing normalized
Refund domain. It does not contact a payment gateway, transfer money, approve a
refund, or perform settlement. Provider and HTTP exposure are outside this
milestone.

No schema change is required. The operation reuses:

- `Refund` for the pending request;
- `RefundEvent` for the customer-visible requested event;
- `RefundEligibility` for the trusted assessment;
- `Payment` and `Order` for normalized ownership and payment state.

Customer ownership remains represented through Refund → Payment → Order →
Customer rather than duplicating customer identity on the refund row.

## Lifecycle

```text
Stage 11 security gates
  -> immutable WriteExecutionContext
  -> InitiateRefundInput validation
  -> RefundPolicy preflight
  -> WriteFrameworkExecutor
  -> SQLAlchemyTransactionManager
  -> lock order row
  -> reload payment, eligibility, and existing refund
  -> RefundPolicy locked recheck
  -> create pending Refund + requested RefundEvent
  -> automatic commit or rollback
  -> standardized WriteResult
  -> safe WriteAuditEvent
```

The business operation never calls `commit()`, `rollback()`, or `flush()`.

## Refund policy

`RefundPolicy` is the single source of initiation decisions. A request requires:

- an existing order owned by the trusted customer;
- order status `delivered`;
- order payment status `paid`;
- a latest normalized payment with status `succeeded`;
- a trusted `RefundEligibility` assessment with status `eligible`;
- no existing refund request for any payment belonging to that order.

Pending payments, failed payments, cancelled or unsupported order states,
missing/negative eligibility, and missing payment facts return the safe
`refund_not_allowed` result. Missing and unowned orders both return
`order_not_found` to prevent enumeration.

## Created records

An approved request atomically creates:

- one `Refund` with status `pending`, request timestamp, payment relationship,
  currency, no processed timestamp, and no settlement amount;
- one related `RefundEvent` with type `requested` and customer-safe wording.

No payment status, order status, processor identifier, or financial balance is
changed.

## Duplicate prevention and concurrency

The preflight avoids a transaction when a refund already exists. The
transactional adapter locks the order row before reloading refund state. Since
all requests for the order serialize on that row, only the first request can
create records.

If an identical request completes after preflight but before lock acquisition,
the locked recheck returns a successful no-change outcome referencing the
existing request timestamp. It creates no second Refund or event. If eligibility
or payment state changes concurrently, execution rolls back safely.

## Audit and privacy

The shared audit event records operation/version, timestamp, request and
correlation IDs, safe order reference, outcome, and safe failure code. It does
not contain payment IDs, currency, amount, processor data, or raw customer
identity. Customer traceability remains connected through the existing Stage 11
correlation chain.

## Future payment integration

A later, separately authorized operation may consume pending requests and call
a payment adapter. That future component can update refund lifecycle states and
events without changing `RefundPolicy`, the initiation operation, or the shared
write framework. Gateway credentials and settlement behavior must remain outside
this customer request operation.

## Extension points

- Extend eligibility centrally in `RefundPolicy`.
- Replace persistence through the reader/store protocols.
- Add partial-refund input only through a separately reviewed business stage.
- Add processor integration behind a provider-neutral payment boundary.
- Preserve order-row locking or an equivalent atomic per-order guarantee.
