# Stage 10 — Customer and Orders Read-Only Capabilities

## Scope

This stage adds provider-independent, read-only business capability contracts
for the Customer and Orders domains. Every successful result is derived from
the existing PostgreSQL repositories. Expected missing-resource and identity
conditions return structured `ToolResult` failures rather than exceptions.

These capabilities do not change the Stage 9 loop, providers, authentication,
database schema, or API surface. The existing composition root now registers
the approved classes through the same `ToolRegistry` path as
`get_order_status`; no alternate discovery or execution mechanism is added.

## Capability-based grounding

Grounding is declared by business capability rather than inferred from concrete
tool names. Each registered business tool publishes immutable
`grounding_capabilities` metadata such as `customer`, `order`, `delivery`, or
`payment`. The policy compares the capabilities required by the current request
with those supplied by tools that completed successfully.

This replaces the earlier fixed lists of recognized tool names. A future Stage
10 tool participates automatically by declaring its grounding capabilities and
being registered normally; neither the grounding policy nor the agent loop must
be edited. Unregistered, disabled, technically failed, and business-failed tool
calls do not count as successful grounding evidence.

## Implemented capabilities

| Capability | Purpose | Trusted boundary | Sensitive-data behavior |
|---|---|---|---|
| `get_customer_profile` | Retrieve display name, language, account state, and membership date | Customer ID comes from `ExecutionContext` | Email, phone, UUID, and addresses are excluded |
| `get_customer_summary` | Retrieve safe profile context and current/history/total order counts | Customer ID comes from `ExecutionContext` | No direct contact or internal identifiers |
| `list_current_orders` | List non-terminal owned orders | Repository filters by trusted customer ID | Address and internal IDs are excluded |
| `get_order_details` | Retrieve one owned order using its order number | Ownership checked before item count | Address, customer ID, and order UUID are excluded |
| `list_order_history` | List delivered and cancelled owned orders | Repository filters by trusted customer ID | Address and internal IDs are excluded |
| `get_order_items` | Retrieve item name, quantity, price, line total, and status | Parent order ownership checked first | Item UUID and internal order UUID are excluded |

Current orders use these existing non-terminal states:

- `pending`
- `confirmed`
- `preparing`
- `dispatched`
- `delayed`

Order history currently means orders in terminal `delivered` or `cancelled`
states. Collections use bounded, deterministic pagination.

## Supported customer questions

The implemented contracts can ground questions such as:

- “What language is set on my profile?”
- “How many current and previous orders do I have?”
- “Show my current orders.”
- “Show my past delivered or cancelled orders.”
- “Give me the details for order ORD-10025.”
- “What items were in ORD-10025?”
- “Was the milk missing or included?”
- “What is the total and payment status of this order?”

The existing `get_order_status` capability remains the focused status and ETA
lookup. These new capabilities do not replace or alter it.

## Validation and failures

All inputs are frozen Pydantic models with unknown fields forbidden. Customer
profile and summary calls include a required intent literal because the existing
provider-neutral selection contract intentionally rejects empty argument
objects; the literal carries no identity or authority.

- Collection limits are positive and bounded.
- Offsets cannot be negative.
- Order numbers are normalized to uppercase and must match supported
  customer-facing formats.
- Model input never includes customer identity.

Stable expected failures include:

| Code | Meaning |
|---|---|
| `customer_identity_required` | Trusted customer identity was not supplied |
| `customer_not_found` | The trusted customer record does not exist |
| `order_not_found` | The order is missing or not owned by the trusted customer |

Missing and unowned orders intentionally share the same public failure to avoid
revealing whether another customer's order exists.

## Repository integration

Existing repositories remain the database boundary:

- `CustomerRepository.get_by_id()` grounds profile and identity checks.
- `OrderRepository` grounds order lookup, customer counts, current orders, and
  terminal order history.
- `OrderItemRepository` grounds item counts and item collections.

The only repository additions are deterministic read-only current/history list
and count queries. No tool contains SQL, commits, flushes, inserts, updates, or
deletes.

## Unsupported capabilities and schema gaps

### Customer addresses

The current `Customer` model has no saved-address relationship. An order stores
only a delivery-address snapshot, which must not be presented as the customer's
address book. A future `CustomerAddress` entity is recommended; no address data
or capability is invented in this stage.

### Order timeline

The current `Order` model has `created_at` and `updated_at`, but no ordered status
history or delivery-event collection. These timestamps cannot reconstruct a
trustworthy timeline. A future `OrderStatusHistory` or Delivery/DeliveryEvent
read model is recommended before implementing timeline questions.

### Additional gaps

- Product IDs, SKUs, and substitution lineage are not represented.
- Delivery tracking is only an order-level ETA snapshot.
- Payment data is only an order-level status snapshot.
- Refund and support-ticket entities are not present.
- Authentication and authorization remain Stage 11.
- All mutations remain Stage 12.

## Verification

Focused tests cover input validation, immutable schemas, safe projections,
trusted identity, ownership, pagination, business failures, repository calls,
current/history filtering, deterministic order, and read-only row counts.

```bash
cd backend
.venv/bin/python -m pytest \
  tests/tools/test_customer_capabilities.py \
  tests/tools/test_order_capabilities.py \
  tests/repositories/test_order_repository.py
.venv/bin/python -m pytest
```

## Recommended Stage 10.3

Design the provider-independent registration/composition policy for approved
read-only business capabilities, or proceed to the next domain read contracts
only after explicitly deciding which capabilities the production runtime may
expose. Do not introduce writes while doing so.
