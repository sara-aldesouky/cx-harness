# Stage 16.4 — Benchmark Reporting API, Exports, and Dashboard

## Architecture

Stage 16.4 is a read-only presentation boundary over the frozen Stage 16.3 reporting engine:

```text
Browser dashboard
  -> /api/v1/benchmark-reporting
  -> BenchmarkPresentationService
  -> BenchmarkReportingService (Stage 16.3)
  -> PostgreSQL analytics records (Stage 16.1)
```

No Stage 16.4 component executes benchmarks, recalculates metrics, changes winner rules, or writes analytics records. JSON, CSV, Excel, and dashboard values all originate from the same immutable Stage 16.3 report contracts. The only direct ORM use is the bounded run-discovery query in the presentation service; export renderers and the browser never import ORM models.

## HTTP API

All routes are under `/api/v1/benchmark-reporting`:

| Method | Route | Purpose |
|---|---|---|
| GET | `/runs` | Discover runs with pagination and evidence-backed filters |
| GET | `/runs/{run_id}` | Return a complete `BenchmarkRunReport` |
| POST | `/comparisons` | Compare 2–8 unique compatible runs |
| GET | `/runs/{run_id}/export.csv` | Download a deterministic ZIP of UTF-8 CSV files |
| GET | `/runs/{run_id}/export.xlsx` | Download a manager-ready Excel workbook |
| POST | `/comparisons/export.csv` | Download comparison CSV ZIP |
| POST | `/comparisons/export.xlsx` | Download comparison workbook |

Run filters include `suite_key`, `suite_version`, `model_name`, `provider_name`, `status`, `created_from`, and `created_to`. Pagination defaults to 25 and is capped at 100. Comparison order is deterministic. The default scoring policy is `cx-deterministic-core` version `1.0.0`; unsupported policy identities fail explicitly.

Example comparison request:

```json
{
  "run_ids": [
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222"
  ],
  "scoring_policy_key": "cx-deterministic-core",
  "scoring_policy_version": "1.0.0"
}
```

Stable failures include `benchmark_run_not_found`, `invalid_scoring_policy`, `comparison_incompatible`, `invalid_date_filter`, `report_generation_failed`, and `export_generation_failed`. Responses do not contain stack traces or database details.

## Dashboard

The Next.js dashboard adds:

- `/benchmark-reporting`: searchable/filterable run discovery, incomplete-state badges, comparison selection, and export action.
- `/benchmark-reporting/runs/{run_id}`: completion, quality, language, category, complexity, pressure, tools, failures, intent, tokens, latency, context/cost, and scoring evidence.
- `/benchmark-reporting/compare?runs={id},{id}`: metric-by-model evidence, compatibility warnings, winner/tie/unavailable explanations, and exports.

Controls are labelled for keyboard and screen-reader use. Missing evidence is rendered as **Unavailable**, not zero. Currency ranking is visibly unavailable when evidence is absent or incompatible, and currency conversion is never attempted.

## Export formats

Single-run CSV downloads are ZIP archives containing ordered files for executive summary, completion, quality, segments, tools, failures, intent, tokens, latency, context, cost, scoring, and metadata. Comparison archives include model overview, metric comparisons, winner explanations, compatibility, and score components.

Single-run Excel workbooks use this deterministic sheet order:

1. Executive Summary
2. Run Completion
3. Quality Metrics
4. Language Breakdown
5. Category Breakdown
6. Complexity Breakdown
7. Pressure Breakdown
8. Tool Performance
9. Failures
10. Intent Analysis
11. Tokens
12. Latency
13. Context
14. Cost
15. Scoring
16. Metadata

Comparison workbooks contain Executive Summary, Model Overview, Metric Comparison, Winner Analysis, Quality, Languages, Tools, Failures, Latency, Cost, Score Components, Compatibility, and Metadata. Workbooks use frozen headers, filters, wrapped text, bounded widths, and explicit unavailable cells. Charts are intentionally omitted: stable, complete evidence tables take precedence, and no chart may imply that absent evidence equals zero.

All stored labels are protected against spreadsheet formula injection. Files are generated in memory, returned directly, and never retained on disk. Filenames contain UTC dates and sanitized model/suite components, preventing traversal.

## Read-only guarantee

- Reporting and export endpoints issue reads only.
- Comparison POST requests are computational and do not represent mutation.
- The SQLAlchemy session is not committed by Stage 16.4.
- Export renderers receive only immutable Stage 16.3 contracts.
- No schema or Alembic migration was added for this stage.

## Local workflow

1. Start local PostgreSQL and apply existing migrations.
2. Start the backend from `backend`: `uvicorn app.main:app --reload`.
3. Set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1` in the frontend environment.
4. Start the dashboard from `frontend`: `npm run dev`.
5. Run or ingest benchmark results using the existing Stage 16.2 workflow.
6. Open `http://localhost:3000/benchmark-reporting`.
7. Open one report or select 2–8 compatible runs.
8. Review evidence and winner explanations, then download CSV ZIP or Excel.

## Verification

```bash
cd backend
.venv/bin/python -m pytest -q tests/benchmark_presentation tests/benchmark_reporting
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app tests

cd ../frontend
npm run typecheck
npm run lint
npm run build

git diff --check
```

PostgreSQL integration tests use the guarded isolated test URL. They must never point at Render or another production database.

## Limitations

- Run-list overall score and score coverage remain unavailable because they require full report generation; they are shown on detail and comparison pages instead of causing N+1 report queries.
- CSV is delivered as a ZIP because flattening the report into one table would destroy evidence structure.
- Generated exports are intentionally uncached and in-memory; very large future suites may require a streaming archive implementation with an explicit size policy.
- Dashboard charting is deferred until a tested chart boundary can retain missing-evidence semantics and metric direction without ambiguity.
