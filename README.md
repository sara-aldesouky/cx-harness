# CX Harness

CX Harness is a monorepo for a customer-experience platform that will compare
AI model behavior against commerce and support workflows.

## Repository architecture

```text
CX-Harness/
├── backend/
│   ├── FastAPI
│   ├── SQLAlchemy
│   ├── Alembic
│   └── PostgreSQL
├── frontend/
│   ├── Next.js
│   ├── React
│   └── TypeScript
└── docs/
```

The `frontend/` directory contains the Next.js application foundation. Feature
pages and backend queries will be implemented in later milestones.

## Backend responsibilities

The backend owns:

- The versioned read-only HTTP API.
- Database models, relationships, migrations, and connection management.
- Repository queries and response serialization.
- Commerce, conversation, model-run, tool-call, and evaluation data.

Backend API routes are exposed under:

```text
/api/v1
```

Interactive API documentation is available at `/docs`, with the OpenAPI
document at `/openapi.json`.

## Frontend responsibilities

The future frontend will own:

- The administrative dashboard and user interface.
- Client-side navigation and presentation.
- Typed integration with the backend's `/api/v1` endpoints.
- Loading, empty, error, filtering, and pagination states.

The frontend will consume backend data over HTTP. It will not connect directly
to PostgreSQL or duplicate backend repository and business rules.

## Documentation

Project documentation and engineering decisions live in `docs/`.

## Backend development

From the repository root:

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/requirements.txt
cp .env.example .env
cd backend
uvicorn app.main:app --reload
```

The local `.env` file and virtual environment are intentionally ignored by Git.

## PostgreSQL tool integration tests

Start the isolated local test database and configure its dedicated URL:

```bash
docker compose -f docker-compose.test.yml up -d --wait
export DATABASE_URL_TEST=\
postgresql://cx_test_user:local_test_password@127.0.0.1:5433/cx_harness_test
```

Apply the existing migrations to that test URL only, then run the marked tests:

```bash
cd backend
DATABASE_URL="$DATABASE_URL_TEST" .venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/python -m pytest -m integration tests/tools/integration
```

The test fixtures also verify and apply the migration head before execution.
They reject non-local hosts, non-test database/user names, and any test URL that
matches `DATABASE_URL`. Stop and remove the disposable service with:

```bash
cd ..
docker compose -f docker-compose.test.yml down -v
```

## ToolCall audit safety and maintenance

Audit input/output payloads recursively redact sensitive keys such as passwords,
tokens, authorization values, API keys, payment-card fields, phone numbers,
emails, and addresses. Safe identity keys such as `order_id`, `execution_id`,
`conversation_id`, and `customer_id` remain available.

`AUDIT_PAYLOAD_MAX_BYTES` defaults to 16 KiB. Sanitized JSON at or below the
limit is stored normally. Larger payloads are replaced by valid truncation
metadata, and `input_truncated` or `output_truncated` is set. The oversized
payload itself is never stored.

`TOOL_CALL_RETENTION_DAYS` defaults to 90 days.
`TOOL_CALL_STALE_AFTER_SECONDS` defaults to 300 seconds. Maintenance is explicit:

```python
from app.database.repositories import ToolCallAuditRepository
from app.database.session import get_session_factory
from app.services import ToolCallAuditMaintenanceService

service = ToolCallAuditMaintenanceService(
    ToolCallAuditRepository(get_session_factory())
)
recovered_count = service.recover_stale()
deleted_count = service.delete_expired()
```

No scheduler, cron job, or automatic deletion process exists yet.

Run the operator command explicitly from `backend/`:

```bash
.venv/bin/python -m scripts.maintain_tool_call_audits dry-run
.venv/bin/python -m scripts.maintain_tool_call_audits recover
.venv/bin/python -m scripts.maintain_tool_call_audits cleanup
.venv/bin/python -m scripts.maintain_tool_call_audits combined --force
```

`cleanup` and `combined` request confirmation before deleting expired records.
Use `--force` only for deliberate non-interactive operation. Combined mode runs
recovery followed by cleanup in one database transaction.
