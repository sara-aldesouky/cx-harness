# Engineering Decisions

This document records important architectural and technical decisions made during the CX Harness project.

## Decision Template

### Decision

Brief description of the decision.

### Context

Why the decision was needed.

### Choice

What was selected.

### Reasoning

Why this option was selected.

### Alternatives Considered

Other options that were considered.

### Consequences

Expected benefits, limitations, or future implications.

## Decision 1 — Managed database

### Context

The project needs persistent storage for customers, orders, conversations, model runs, tool calls, and evaluation results.

### Choice

Render PostgreSQL.

### Reasoning

The database is already available, managed, accessible from local development, and suitable for the prototype.

### Consequences

Local development will connect to a remote managed PostgreSQL instance through environment variables.

## Decision 2 — Local model development

### Context

Qwen and potentially Fanar need to be tested locally before production deployment is selected.

### Choice

Ollama for local open-model testing during development.

### Reasoning

Ollama provides a simple local inference API and uses the developer's laptop hardware.

### Consequences

A backend deployed on Render will not be able to access the laptop's localhost Ollama instance. A remote inference endpoint will be required for a fully deployed version.

## Decision 3 — Delay provider implementations

### Context

The final inference methods for Gemini, Qwen, and Fanar have not been decided.

### Choice

Keep only a generic provider placeholder for now.

### Reasoning

Creating provider-specific implementations now would introduce premature architectural assumptions.

### Consequences

Provider adapters will be added only after their deployment and API methods are defined.

## Decision 4 — Isolated local test database

### Context

Automated database tests must not read from or write to the shared Render development database.

### Choice

Run a disposable PostgreSQL 16 test database through Docker Compose on
`127.0.0.1:5433`.

### Reasoning

A dedicated local instance keeps test transactions and future destructive
constraint checks isolated from development data while remaining easy to
recreate.

### Consequences

Database tests require Docker and an explicit `DATABASE_URL_TEST`. The test
fixtures never fall back to `DATABASE_URL`, and the Docker volume can be
removed when a completely fresh test database is needed.
