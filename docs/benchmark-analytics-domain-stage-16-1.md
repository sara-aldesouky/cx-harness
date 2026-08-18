# Stage 16.1 — Benchmark Analytics Domain and Data Architecture

## Boundary and source of truth

PostgreSQL is the source of truth for reproducible benchmark analytics. The
subsystem is isolated under `app.benchmark_analytics`; it is not connected to
the benchmark runner, production conversations, providers, tools, Excel, or a
dashboard. Repositories expose immutable domain contracts and never expose ORM
instances.

```text
Benchmark Suite
      │
      └── Benchmark Run
              │
              ├── Conversation Results
              │       ├── Provider Turns
              │       ├── Tool Executions
              │       ├── Metric Results
              │       └── Failure Events
              │
              └── Future Analytics and Exports
```

Suites are reusable versioned datasets. A run captures one model/provider
configuration and an immutable pricing snapshot. One conversation result is
stored per `(run, test case)`. Turns and tools retain deterministic ordinal
positions. Extensible metric rows prevent schema changes for each new metric.

## Relationships and deletion

- Suite → run uses `RESTRICT`; a suite with historical runs cannot be deleted.
- Run → all analytics descendants uses `CASCADE`.
- Optional failure links to turns/tools use `SET NULL`, preserving the failure.
- `source_conversation_id` is a non-FK UUID. Analytics can correlate a source
  when permitted, but analytics deletion can never delete production data.
- No analytics table has a foreign key to customer, order, payment, refund, or
  production conversation tables.

## Contracts

Contracts are frozen Pydantic models with forbidden unknown fields, explicit
enums, UTC timestamps, deterministic JSON, and Decimal money. Configuration
and pricing snapshots preserve the exact assumptions used by a run. Prices are
snapshots because historical results must not change when current prices do.

API pricing supports per-token and request charges. Self-hosted pricing retains
hardware, electricity, and hosting assumptions; Stage 16.1 deliberately does
not calculate final cost.

## Metrics

Automatically measurable values include tokens, latency, turn/tool counts,
schema and authorization outcomes, business failures, runtime termination, and
cost inputs.

Intent quality, reasoning, hallucination, language quality, clarification,
helpfulness, and task completion require an evaluator. Every metric records its
definition version, method (`deterministic_rule`, automated/model evaluator,
human review, or imported annotation), evaluator identity/version, and
sanitized evidence. A definition change requires a new metric version.

## Failure ownership

Failure category and responsibility are independent. For example,
`business_data/payment_not_found` belongs to `business_data`, not the harness.
Responsibility layers distinguish model, provider, business capability,
business data, harness, security, evaluation pipeline, and unknown ownership.
This prevents business-data gaps from reducing infrastructure reliability.

## Privacy

Snapshots, metadata, sanitized arguments, result summaries, and metric evidence
reject sensitive keys and unmasked public order references. Raw phone numbers,
emails, addresses, customer identifiers, credentials, access tokens, API keys,
and provider secrets are forbidden. Only masked report-facing references are
allowed. Analytics performs no production business writes.

## Future flow

Stage 16.2 may translate completed benchmark execution artifacts into these
repositories. Later stages may query PostgreSQL to generate Excel workbooks,
charts, dashboards, and model comparisons. Those presentation layers must stay
downstream and must never become an alternative source of truth.
