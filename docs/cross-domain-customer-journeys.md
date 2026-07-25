# Stage 10.7 — Cross-Domain Customer Journeys

## Execution lifecycle

```text
Customer request
  → declarative evidence classification
  → ordered provider-neutral tool selections
  → customer-scoped PostgreSQL reads
  → approved knowledge reads
  → ordered ToolResult continuation
  → one grounded customer response
```

The existing bounded loop coordinates every journey. No journey-specific
orchestration, provider logic, repository, schema, or response composer is
introduced. Tool order is preserved through selection, execution, audit, and
continuation.

## Verified journeys

| Journey | Transactional evidence | Policy evidence |
|---|---|---|
| Delayed order and cancellation | Order, Delivery | Cancellation policy |
| Failed payment and apparent deduction | Payment, Order | Failed-payment FAQ |
| Missing item and refund eligibility | Order Items, Delivery, Refund | Missing-item FAQ |
| Refund status and processing time | Refund | Refund processing policy |
| Address change and current delivery | Customer, Order, Delivery | Address-change policy |

Transactional tools remain authoritative for the customer's current state.
Knowledge tools explain only general company rules. Mixed questions must satisfy
both evidence classes before the model's final answer is accepted.

## Response composition and failures

The provider receives ordered, structured results and produces one concise
answer. Tests verify exact tool ordering, unique call identity, one execution per
selection, and no duplicate repository calls. Conflicting records are stated
explicitly instead of silently choosing one source.

Missing orders, deliveries, refunds, or policies terminate through the existing
structured business-failure path. Remaining calls are not executed after the
failure, preventing unnecessary work and preventing an ungrounded continuation.

## Scope

This stage adds integration verification and declarative grounding vocabulary
only. It adds no domain, schema, authentication, write operation, provider
behavior, or Stage 9 orchestration change.
