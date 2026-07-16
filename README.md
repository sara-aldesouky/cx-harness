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
│   ├── Next.js (planned)
│   ├── React (planned)
│   └── TypeScript (planned)
└── docs/
```

The `frontend/` directory is currently an empty placeholder. The frontend
framework and its dependencies will be initialized in a later milestone.

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
