# Stage 10.4 — Payment Read Capabilities

## Business model

```text
Customer 1 ── * Order 1 ── * Payment 1 ── * PaymentEvent
```

- `Payment` represents one payment attempt, allowing an order to have retries.
- `PaymentEvent` represents ordered customer-visible lifecycle changes across
  authorization, capture, failure, and refund states.
- The existing `Order.payment_status` remains a commerce snapshot. Payment tools
  use normalized payment data as their trusted source.

The CX read model stores no processor token, processor transaction identifier,
card number, security code, or sensitive metadata. Only broad method types such
as `card`, `cash`, `wallet`, and `bank_transfer` may be returned.

## Repository boundary

`PaymentRepository` owns latest-attempt lookup with customer ownership, latest
event lookup, and deterministic event history across all attempts for an order.
Tools contain no SQL and perform no inserts, updates, deletes, commits, or
flushes.

## Runtime capabilities

| Tool | Customer-safe result |
|---|---|
| `get_payment_status` | Latest successful, refunded, or partially-refunded state |
| `get_payment_method` | Broad payment method type only |
| `get_payment_summary` | Status, method, amount, currency, and public failure reason |
| `get_payment_history` | Paginated public events across payment attempts |
| `get_latest_payment_event` | Latest public payment or refund event |

Pending and failed status checks return structured business failures so the
existing loop produces safe customer-facing messages. Other expected failures
include `payment_not_found`, `payment_history_empty`, and
`payment_method_unavailable`.

## Grounding and runtime integration

Payment tools are registered through the existing runtime composition and use
the existing ToolRegistry, executor, audit, continuation, and ToolResult
contracts. Metadata declares `ORDER` and `PAYMENT`; tools capable of answering
refund-state questions also declare `REFUND`. The existing capability policy
therefore recognizes them automatically without tool-name mappings or policy
changes.

## Scope boundaries

This stage does not process payments, contact a processor, expose credentials,
add APIs, add authentication, or implement any write operation.
