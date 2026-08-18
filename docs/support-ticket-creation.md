# Support Ticket Creation

## Scope

`create_support_ticket` creates one customer support ticket when automation
cannot fully resolve an issue or the customer requests human assistance. It does
not assign an agent, send messages, implement case workflow, or expose provider
or HTTP integration.

Because no support-ticket persistence existed, this milestone adds one minimal
normalized `support_tickets` table. No existing business model is redesigned.

## Lifecycle

```text
Stage 11 security gates
  -> immutable WriteExecutionContext
  -> strict CreateSupportTicketInput
  -> SupportTicketPolicy preflight
  -> WriteFrameworkExecutor
  -> SQLAlchemyTransactionManager
  -> lock trusted customer (+ related order when supplied)
  -> duplicate and ownership recheck
  -> create one open SupportTicket
  -> automatic commit or rollback
  -> standardized WriteResult
  -> safe WriteAuditEvent
```

The operation does not call `commit()`, `rollback()`, or `flush()`.

## Validation rules

- Customer identity comes only from `WriteExecutionContext` and must exist.
- An optional order number is normalized and must belong to that customer.
- Supported categories are `general_inquiry`, `order_issue`, `delivery_issue`,
  `payment_issue`, `refund_issue`, and `technical_issue`.
- Supported escalation reasons are `customer_requested`, `automation_failed`,
  `unresolved_issue`, and `operation_blocked`.
- Issue text is whitespace-normalized, printable, and 10–2,000 characters.
- Missing and unowned related orders both return `order_not_found`.

The issue description is stored for future case handling but is excluded from
the public result and audit event.

## Priority assignment

`SupportTicketPolicy.priority()` is the only priority decision point:

- `general_inquiry`: low;
- order, delivery, and technical issues: medium;
- payment and refund issues: high;
- an `operation_blocked` escalation: high regardless of category.

The schema supports critical priority for future reviewed policies, but this
creation stage does not infer critical incidents from untrusted customer text.

## Duplicate prevention and idempotency

A SHA-256 issue fingerprint is derived from normalized category, optional order
number, and case-folded issue text. It is never returned publicly. Active means
`open` or `in_progress`.

Duplicate protection has two layers:

1. Preflight returns `support_ticket_already_exists` without a transaction.
2. The transaction locks the customer row, reloads active duplicates, and is
   backed by a partial unique index on customer and issue fingerprint.

Concurrent identical requests therefore serialize. The first creates a ticket;
the second returns the existing customer-safe reference and creates no row.
Resolved or closed tickets do not permanently prevent a later new case.

## Ticket reference and persistence

References use `TKT-` plus an uppercase random identifier and have a unique
database index. Each ticket stores the customer relationship, optional order
relationship, category, priority, open status, issue text, private fingerprint,
and timestamps.

Deleting a customer is restricted while tickets exist. Deleting an order clears
the optional relationship rather than deleting the support record.

## Audit and privacy

The write event records operation/version, timestamp, request/correlation IDs,
ticket reference, optional safe order number, outcome, and safe failure code. It
does not contain the issue text, internal UUIDs, customer PII, or internal notes.

## Future workflow extension points

- Assignment and routing can consume open tickets without changing creation.
- Workflow services may transition status under separately authorized writes.
- Comments and case messages require separately reviewed normalized entities.
- SLA/critical priority policy can extend `SupportTicketPolicy` centrally.
- Read capabilities require a separate Stage 10-style privacy review.
