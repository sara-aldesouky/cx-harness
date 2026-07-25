# Stage 10.5 — Refund Read Capabilities

## Business model

```text
Customer → Order → Payment → Refund → RefundEvent
                 Order → RefundEligibility
```

`Refund` records one refund against a payment and supports multiple partial or
full refunds. `RefundEvent` is its chronological customer-visible lifecycle.
`RefundEligibility` stores the latest trusted business assessment for an order.
The harness never computes policy eligibility and never approves, rejects, or
executes a refund.

Refund data references Payment rather than duplicating payment method or
processor state. No processor identifiers, internal IDs, security fields, or
private audit metadata are exposed by tool outputs.

## Repository boundary

`RefundRepository` provides deterministic, customer-owned lookups for the
latest refund, paginated refund history, latest public event, and eligibility
assessment. Every method is SELECT-only. Tools contain no SQL.

## Runtime capabilities

| Tool | Result |
|---|---|
| `get_refund_status` | Latest completed status or structured pending/rejected failure |
| `get_refund_summary` | Customer-safe amount, currency, full/partial type, reason, and dates |
| `get_refund_history` | Deterministically ordered refunds for the owned order |
| `get_latest_refund_event` | Latest customer-visible lifecycle event |
| `check_refund_eligibility` | Stored business eligibility assessment only |

Expected failures use the existing `ToolResult` contract:
`refund_not_found`, `refund_pending`, `refund_rejected`,
`refund_history_empty`, `refund_not_eligible`, and
`refund_amount_unavailable`.

## Grounding and integration

The five tools are registered through the existing runtime composition. Their
metadata declares refund evidence, alongside order/payment evidence required by
owned order-number questions. The existing capability-based policy recognizes
them without tool-name mappings or grounding-policy changes.

## Scope boundary

These capabilities read trusted PostgreSQL data only. They do not change refund
state, issue money, call a payment processor, make policy decisions, or add
authentication, provider, or orchestration behavior.
