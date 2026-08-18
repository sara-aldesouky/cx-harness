# Stage 16.3 — Benchmark Aggregation and Model Comparison

## Boundary

Stage 16.3 is a read-only reporting subsystem over Stage 16.1 PostgreSQL records.
It consumes Stage 16.2 deterministic metrics but never changes analytics rows.

```text
PostgreSQL analytics records
        ↓
Typed read-only snapshot
        ↓
Deterministic aggregation
        ↓
Version-aware scoring
        ↓
Compatibility-checked comparison
        ↓
Immutable reporting datasets
```

The reporting datasets are the future input to Excel, charts, and dashboards.
Those presentation layers are not implemented here.

## Aggregation semantics

Run reports separate completion, outcome, metrics, language, category, tool,
failure, token, latency, context, cost, complexity, pressure, and intent views.
Failure rates deduplicate affected conversations. Metric identities include key,
version, method, evaluator, and evaluator version, so incompatible definitions
are never silently averaged.

Boolean metrics report true/false rates. Numeric metrics report mean, median,
range, population standard deviation, and normalized average. Categorical metrics
retain a distribution. Missing segments remain absent rather than being reported
as zero-performing groups.

## Latency and context

Wall-clock benchmark duration, accumulated conversation latency, provider latency,
and tool latency are distinct fields. Percentiles are interpolated over stored
conversation latency. Context usage comes from actual provider-turn context tokens
and utilization ratios; configured window size is not treated as consumption.

## Costs

Cost summaries require complete stored costs and one currency. Missing self-hosted
allocation remains unavailable, never free. Different currencies make direct cost
ranking unavailable. No currency conversion is performed.

## Scoring policy

`ScoringPolicy` is immutable and versioned. Weights must total one. It records
missing-metric behavior, minimum evidence, normalization metadata, and exclusions.
Missing dimensions are either excluded with transparent re-normalization or make
the score unavailable. Reports expose score coverage and every weighted component.
Changing weights requires a new policy version.

## Comparison and winners

Runs may be compared only when suite key, version, content hash, expected test
count, and stored metric definitions are compatible. Winner selection is
dimension-specific and states eligibility, runner-up, difference, and ties.
Unavailable or incompatible evidence produces `winner unavailable`; the engine
does not invent one universal winner.

## Known source limitations

Stage 16.1 stores token counts as non-null integers, so legacy records cannot
distinguish a measured zero from unavailable usage. Stage 16.3 preserves optional
context and cost values, but does not reinterpret existing zero token fields.
Topic-switch and multi-intent analyses require explicit stored evidence not present
in the frozen schema and are therefore not inferred from transcripts.

## Future flow

Stage 16.4 may consume `ReportingDataset` for export or presentation. This stage
does not generate Excel, charts, dashboards, subjective judgments, or benchmarks.
