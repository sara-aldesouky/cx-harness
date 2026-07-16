# Database Architecture

[Project overview](PROJECT_OVERVIEW.md) · [Backend](BACKEND_ARCHITECTURE.md) · [AI pipeline](AI_PIPELINE.md)

## Diagram 7 — Entity relationship model

```mermaid
erDiagram
  CUSTOMERS {
    uuid id PK
    string email UK
    string phone UK
    string preferred_language
    boolean is_active
  }
  ORDERS {
    uuid id PK
    uuid customer_id FK
    string order_number UK
    string status
    string payment_status
    decimal total_amount
  }
  ORDER_ITEMS {
    uuid id PK
    uuid order_id FK
    string product_name
    int quantity
    decimal unit_price
    string item_status
  }
  CONVERSATIONS {
    uuid id PK
    uuid customer_id FK
    uuid related_order_id FK
    string status
    string channel
    string active_model
  }
  MESSAGES {
    uuid id PK
    uuid conversation_id FK
    string role
    text content
    int sequence_number
  }
  MODEL_RUNS {
    uuid id PK
    uuid conversation_id FK
    string provider
    string model_name
    string status
    int total_tokens
  }
  TOOL_CALLS {
    uuid id PK
    uuid model_run_id FK
    string tool_name
    string status
    jsonb input_json
    jsonb output_json
  }
  EVALUATIONS {
    uuid id PK
    uuid model_run_id FK
    string evaluator_type
    string evaluator_name
    decimal overall_score
    boolean passed
  }

  CUSTOMERS ||--o{ ORDERS : "owns (RESTRICT delete)"
  CUSTOMERS ||--o{ CONVERSATIONS : "starts (RESTRICT delete)"
  ORDERS ||--|{ ORDER_ITEMS : "contains (CASCADE delete)"
  ORDERS o|--o{ CONVERSATIONS : "relates to (SET NULL)"
  CONVERSATIONS ||--o{ MESSAGES : "contains (CASCADE delete)"
  CONVERSATIONS ||--o{ MODEL_RUNS : "records (CASCADE delete)"
  MODEL_RUNS ||--o{ TOOL_CALLS : "requests (CASCADE delete)"
  MODEL_RUNS ||--o{ EVALUATIONS : "receives (CASCADE delete)"
```

### Plain-English explanation

Customers place orders and start support conversations. Orders contain items. Conversations contain messages and model runs. Each model run can record tool calls and evaluations.

### Engineering explanation

UUID primary keys avoid sequence coupling. Foreign keys enforce ownership. Commerce parents use restrictive deletion where history should be protected. Dependent operational telemetry uses cascading deletion. A conversation’s optional related order uses `SET NULL`, preserving the conversation if an order relationship is removed.

### Why this architecture

The schema separates business truth (customers and orders), interaction history (conversations and messages), and AI observability (runs, calls, evaluations).

### Benefits

- Referential integrity
- Auditable model execution chain
- Independent model comparisons
- Clear cascade semantics
- Extensible JSONB tool payloads

### Tradeoffs

- Joins are required for full end-to-end reports
- Flexible JSONB payloads have weaker column-level typing
- Deletion rules require careful operational understanding

## Migration management

Alembic is the only schema-change mechanism. The current chain is linear and culminates in the Evaluation migration. Both Render development PostgreSQL and the Docker test database use the same revisions; application code never calls `create_all`.

