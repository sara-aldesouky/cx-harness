# Stage 10.3 — Delivery Read Capabilities

## Business model

Stage 10.3 introduces a normalized, read-only Delivery domain:

```text
Customer 1 ── * Order 1 ── 0..1 Delivery 1 ── * DeliveryEvent
```

- `Delivery` owns current delivery status, ETA, and an optional valid window.
- `DeliveryEvent` stores ordered, customer-visible updates. An event with type
  `delivery_attempted` represents an attempted delivery; no separate attempt
  table is needed for the current read requirements.
- Deleting an order cascades to its delivery and events.
- Internal UUIDs never appear in tool output.

The existing `Order.estimated_delivery_time` is retained as a legacy commerce
snapshot. Delivery tools read the normalized Delivery aggregate and do not
expand or denormalize the Order table.

## Repository responsibility

`DeliveryRepository` is the only persistence boundary used by delivery tools.
It provides owned order-number lookup, latest-event lookup, deterministic event
history, and event counts. Tools contain no SQL and perform no commit, flush,
insert, update, or delete operation.

## Runtime capabilities

| Tool | Customer-safe result |
|---|---|
| `get_delivery_status` | Current status, delayed flag, last update time |
| `get_delivery_eta` | Current estimated arrival timestamp |
| `get_delivery_window` | Scheduled start and end timestamps |
| `get_latest_delivery_event` | Latest public event description and timestamp |
| `get_delivery_history` | Reverse-chronological paginated public events |

All inputs use a customer-facing order number. Customer identity comes only
from trusted `ExecutionContext.customer_id`, and repository lookup enforces
ownership without revealing whether another customer's delivery exists.

## Grounding and failures

Every tool declares both `GroundingCapability.ORDER` and
`GroundingCapability.DELIVERY`: customer wording commonly references an order,
while the returned facts belong to Delivery. Runtime composition builds the
policy from enabled registry metadata, so these tools are recognized without
changing grounding or orchestration code.

Expected failures use existing structured `ToolResult` errors:

- `delivery_not_found`
- `delivery_not_started`
- `eta_unavailable`
- `delivery_window_unavailable`
- `delivery_history_empty`

These are normal business outcomes rather than Python exceptions.

## Scope boundaries

No driver identity, precise live location, internal operational notes, write
operations, provider logic, authentication, or authorization behavior is added.
