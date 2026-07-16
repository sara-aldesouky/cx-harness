# Data Flow

[System architecture](SYSTEM_ARCHITECTURE.md) · [Frontend](FRONTEND_ARCHITECTURE.md) · [Backend](BACKEND_ARCHITECTURE.md)

## Diagram 8 — API request flow

```mermaid
sequenceDiagram
  actor User
  participant Page as Orders Page
  participant RQ as React Query
  participant AX as Axios
  participant API as FastAPI Router
  participant Repo as OrderRepository
  participant ORM as SQLAlchemy
  participant DB as PostgreSQL

  User->>Page: Clicks Orders
  Page->>RQ: Request orders query
  RQ->>AX: Execute cache miss/refetch
  AX->>API: GET /api/v1/orders?limit=20&offset=0
  API->>Repo: list_orders() + count_orders()
  Repo->>ORM: Build validated SELECT statements
  ORM->>DB: Execute queries
  DB-->>ORM: Rows + total
  ORM-->>Repo: Order objects
  Repo-->>API: Deterministic result
  API-->>AX: Pydantic-validated JSON
  AX-->>RQ: Paginated response
  RQ-->>Page: Cached data/state
  Page-->>User: Orders table appears
```

### Plain-English explanation

Clicking Orders triggers one cached request. The backend reads the database and returns a validated paginated response. The browser then renders the table.

### Engineering explanation

React Query de-duplicates and caches requests by endpoint, page, page size, and server filters. Axios applies the shared base URL. FastAPI validates query parameters, repositories validate domain filters, and Pydantic serializes the response.

### Why this architecture

The flow gives every layer one responsibility and makes loading, retry, error, pagination, and refresh behavior reusable.

### Benefits

- No duplicate page-specific fetch logic
- Cache-aware refresh
- Deterministic pagination
- Consistent validation and errors
- Observable request path

### Tradeoffs

- More hops than direct database access
- Cache keys and backend parameters must remain aligned

## Diagram 9 — Testing architecture

```mermaid
flowchart TB
  PYTEST[pytest suite]
  GUARD[DATABASE_URL_TEST safety guard]
  ALEMBIC[Alembic migrations]
  DB[(Docker PostgreSQL on 127.0.0.1:5433)]
  TX[Per-test transaction]
  MODELS[Model and constraint tests]
  REPOS[Repository integration tests]
  API[FastAPI API tests]
  ROLLBACK[Automatic rollback]
  COV[Coverage report]
  RENDER[(Render development DB)]

  PYTEST --> GUARD --> ALEMBIC --> DB
  DB --> TX
  TX --> MODELS
  TX --> REPOS
  TX --> API
  MODELS --> ROLLBACK
  REPOS --> ROLLBACK
  API --> ROLLBACK
  PYTEST --> COV
  GUARD -. blocks access .-> RENDER
```

### Plain-English explanation

Tests use a disposable local PostgreSQL database, not the shared Render database. Each test rolls its work back.

### Engineering explanation

`DATABASE_URL_TEST` is mandatory and never falls back to `DATABASE_URL`. Alembic prepares the test schema. Fixtures provide transactional sessions; model, repository, schema, and API integration tests run against PostgreSQL behavior and roll back afterward.

### Why this architecture

SQLite would not faithfully test PostgreSQL UUID, JSONB, constraint, and cascade behavior. Isolation protects shared development data.

### Benefits

- Production-representative database behavior
- Safe destructive constraint tests
- Independent tests
- Reliable coverage metrics
- Render remains untouched

### Tradeoffs

- Docker must be running
- Integration tests are slower than pure unit tests
- Test migrations must stay synchronized with local heads

