# Stage 16.2 — Automated Benchmark Result Ingestion

## Architecture

Stage 16.2 is an application boundary between normalized, completed benchmark
execution artifacts and the frozen Stage 16.1 analytics domain. It is deliberately
independent of Qwen, Ollama, business repositories, tool execution, and reporting.

```text
Benchmark Runner
      │
      ▼
Normalized Execution Artifact
      │
      ▼
Ingestion Validation
      │
      ├── Sanitization
      ├── Mapping
      ├── Cost Calculation
      └── Failure Classification
      │
      ▼
Atomic Analytics Persistence
      │
      └── PostgreSQL
```

The future benchmark runner will translate provider/runtime output into the
immutable contracts in `app.benchmark_ingestion.contracts`. The ingestion core
never receives or persists provider-native payloads.

## Input contracts

`BenchmarkRunIdentity` fixes suite, model, provider, deployment, configuration,
and pricing identity. `CompletedConversationExecution` owns normalized ordered
provider turns, tool attempts, termination evidence, deterministic evaluation
signals, and optional caller totals used only for reconciliation. All contracts
are immutable and reject unknown fields.

## Ingestion flow and transactions

`BenchmarkIngestionService` exposes `create_run`, `start_run`,
`ingest_conversation`, `ingest_batch`, `ingest_request`, `retry_failed_item`,
`get_ingestion_status`, and `finalize_run`.

Each conversation uses one PostgreSQL savepoint containing its conversation row,
provider turns, tool executions, deterministic metrics, and failure events. A
child failure rolls back the complete unit. Batch processing preserves completed
conversations and reports failed items separately.

## Idempotency

Natural identities remain those established by Stage 16.1: run key, run/test-case,
turn number, execution order, and versioned metric identity. Equivalent retries
return an idempotent no-op. Conflicting reuse of a run or test-case identity fails
closed. The service never appends duplicate children.

## Lifecycle

Runs move from `created` to `running`, then to `completed`,
`partially_completed`, or `failed`. Immutable identity/configuration/pricing
snapshots are compared when a run key is reused. Terminal runs reject ingestion.
Finalization compares stored conversations with the frozen suite test-case count.

`passed` means deterministic benchmark acceptance criteria were satisfied. It is
not synonymous with runtime completion. Business-data, model, infrastructure,
and security failures retain independent category and responsibility fields.

## Mapping and deterministic metrics

Mappers recompute token totals, latency, provider/tool counts, success/failure
counts, outcome flags, and cost. Supplied totals must reconcile. Initial metrics
include tool execution/selection/argument/authorization rates, response validity,
completion, clarification count, token counts, latency, context utilization,
grounding, continuity, and estimated cost when available.

No subjective reasoning, language, helpfulness, emotional-intelligence, or
semantic hallucination score is manufactured. Such values require a later
evaluator and retain their own evaluation method.

## Failure ownership

Structured runtime signals map explicitly to `FailureCategory`, severity, and
`ResponsibilityLayer`. Related turn/tool identities are linked after normalized
ordering is validated. Failure descriptions pass through the privacy boundary.
Business-data absence does not automatically become an infrastructure failure.

## Sanitization

Central sanitization defensively copies metadata and rejects sensitive keys,
emails, phone numbers, addresses, secrets, authorization values, database URLs,
customer IDs, and unmasked public order references. Masked references and safe
internal UUID link fields are permitted. Logs contain lifecycle labels and counts,
not artifacts or identifiers.

## Pricing

Managed API cost uses `Decimal` and the immutable run pricing snapshot:

```text
input tokens × input price per million
+ output tokens × output price per million
+ request count × request charge
```

Currency is preserved without conversion. Missing pricing produces no cost, not
zero. Self-hosted cost remains unset until sufficient measured allocation inputs
exist; hardware is never represented as free.

## Controlled backfill

`python -m scripts.backfill_stage_15_3_analytics` imports a deterministic,
sanitized two-case Stage 15.3 demonstration into local PostgreSQL only. Repeating
the command is idempotent. `--cleanup` removes the demonstration run. The command
rejects non-local database hosts and contains no customer transcript or business
mutation.

## Future integration

Stage 16.3 may aggregate stored records for comparisons. Excel, charts, dashboard
views, subjective judging, and the 100-case benchmark remain intentionally absent.
