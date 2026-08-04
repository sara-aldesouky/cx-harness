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

## CX Harness Architecture

The diagram starts with the real customer-serving runtime. The separately
grouped benchmark pipeline sends controlled cases through that same runtime,
then stores and reports the measured evidence without changing production
behavior:

```mermaid
%% CX Harness — execution-flow architecture
%% Production runtime and benchmark evaluation are deliberately separate.
%%{init: {"theme":"dark","flowchart":{"curve":"linear","nodeSpacing":38,"rankSpacing":54,"htmlLabels":true},"themeVariables":{"background":"#0d1117","primaryColor":"#21262d","primaryTextColor":"#e6edf3","primaryBorderColor":"#8b949e","lineColor":"#8b949e","secondaryColor":"#161b22","tertiaryColor":"#161b22","clusterBkg":"#0d1117","clusterBorder":"#30363d","fontFamily":"Arial, sans-serif","fontSize":"15px"}}}%%
flowchart TB

  subgraph RUNTIME["CX HARNESS RUNTIME ───"]
    direction TB

    subgraph ENTRY["PHASE 1 · REQUEST ───"]
      direction LR
      CUSTOMER["<b>Customer Application</b><br/>Sends the customer message"]
      API["<b>FastAPI Endpoint</b><br/>Validates the HTTP request"]
      AUTHN["<b>Authentication</b><br/>Verifies the caller"]
      IDENTITY["<b>Trusted Identity</b><br/>Creates application-owned identity"]
      MAPPER["<b>API Mapper</b><br/>Maps transport to application input"]
      SERVICE["<b>ModelPipelineService</b><br/>Starts the support use case"]
      CUSTOMER --> API --> AUTHN --> IDENTITY --> MAPPER --> SERVICE
    end

    subgraph INVOCATION["PHASE 2 · MODEL ───"]
      direction LR
      PRIVIN["<b>Data Protection</b><br/>Minimizes sensitive input"]
      CONTEXT["<b>Context Builder</b><br/>Adds prompt and ordered history"]
      PROVIDER1["<b>Provider Adapter</b><br/>Ollama · Gemini · future providers"]
      QWEN1["<b>Model</b><br/>Returns an answer or tool requests"]
      PRIVIN --> CONTEXT --> PROVIDER1 --> QWEN1
    end

    TOOLQ{"<b>Tool requested?</b>"}

    subgraph SECURE["PHASE 3 · SECURE TOOLS ───"]
      direction TB
      subgraph TRUST["3A · TRUSTED SELECTION ───"]
        direction LR
        SELECTION["<b>ToolSelection</b><br/>Normalizes the model request"]
        REGISTRY["<b>ToolRegistry</b><br/>Allows registered, enabled tools"]
        STATE["<b>Conversation State</b><br/>Supplies remembered verified context"]
        RESOLVER["<b>Entity Resolver</b><br/>Verifies the referenced business entity"]
        BINDER["<b>Trusted Argument Binder</b><br/>Injects trusted protected values"]
        SCHEMA["<b>Schema Validation</b><br/>Validates the bound arguments"]
        SELECTION --> REGISTRY --> RESOLVER --> BINDER --> SCHEMA
      end
      subgraph ACCESS["3B · ACCESS ───"]
        direction LR
        ROLE["<b>Role Policy</b><br/>Checks capability access by role"]
        TOOLA["<b>Tool Authorization</b><br/>Checks permission for this tool"]
        OWNER["<b>Ownership Authorization</b><br/>Checks access to this resource"]
        ROLE --> TOOLA --> OWNER
      end
      subgraph BUSINESS["3C · BUSINESS DATA ───"]
        direction LR
        CAPABILITY["<b>Business Capability</b><br/>Runs customer-support logic"]
        REPOSITORY["<b>Repository</b><br/>Encapsulates database access"]
        ORM["<b>SQLAlchemy</b><br/>Translates Python queries to SQL"]
        POSTGRES[("<b>PostgreSQL</b><br/>Source of business truth")]
        CAPABILITY --> REPOSITORY --> ORM --> POSTGRES
      end

      SCHEMA --> ROLE
      OWNER --> CAPABILITY
      STATE -. "verified context" .-> RESOLVER
    end

    subgraph RESPONSE["PHASE 4 · RESPONSE ───"]
      direction LR
      RESULT["<b>ToolResult</b><br/>Returns safe structured evidence"]
      GROUND["<b>Grounding Policy</b><br/>Requires trusted business evidence"]
      CONTINUE["<b>Continuation Builder</b><br/>Adds the tool result to the conversation"]
      PROVIDER2["<b>Provider Adapter</b><br/>Builds the continuation request"]
      QWEN2["<b>Model</b><br/>Writes language from verified evidence"]
      PRIVOUT["<b>Data Protection</b><br/>Protects the final output"]
      FINAL["<b>Customer Response</b><br/>Returns a safe grounded answer"]
      RESULT --> GROUND --> CONTINUE --> PROVIDER2 --> QWEN2 --> PRIVOUT --> FINAL
    end

    subgraph INFRA["PHASE 5 · RUNTIME CONTROLS ───"]
      direction LR
      ORCH["<b>Orchestration</b><br/>Controls bounded turns and tool cycles"]
      EXECSTATE["<b>Execution State</b><br/>Tracks turns and completed work"]
      LIMITS["<b>Cancellation & Timeouts</b><br/>Stop work predictably"]
      TRACE["<b>Tracing & Logging</b><br/>Records a safe execution timeline"]
      AUDIT["<b>Security Auditing</b><br/>Records security events without PII"]
      CLEAN["<b>Cleanup</b><br/>Releases temporary resources"]
      ORCH --- EXECSTATE --- LIMITS --- TRACE --- AUDIT --- CLEAN
    end

    SERVICE --> PRIVIN
    QWEN1 --> TOOLQ
    TOOLQ -- "YES" --> SELECTION
    POSTGRES --> RESULT
    TOOLQ -- "NO" --> PRIVOUT
    FINAL ~~~ ORCH
  end

  subgraph BENCHMARK["BENCHMARK PIPELINE · SEPARATE FROM RUNTIME ───"]
    direction TB
    subgraph CAMPAIGN["CAMPAIGN ───"]
      direction LR
      RUNNER["<b>Benchmark Runner</b><br/>Coordinates controlled campaigns"]
      CASE["<b>Benchmark Case</b><br/>One versioned customer scenario"]
      REAL["<b>Real CX Harness Execution</b><br/>Invokes production phases 1–5 above"]
      EXECUTION["<b>Conversation Execution</b><br/>Captures the measured outcome"]
      RUNNER --> CASE --> REAL --> EXECUTION
    end
    subgraph INGEST["INGESTION ───"]
      direction LR
      ARTIFACT["<b>Artifact Creation</b><br/>Normalizes provider-neutral evidence"]
      VALIDATE["<b>Validation</b><br/>Checks evidence consistency"]
      SANITIZE["<b>Sanitization</b><br/>Removes PII and secrets"]
      COST["<b>Cost Calculation</b><br/>Applies the saved pricing snapshot"]
      STORE[("<b>Atomic PostgreSQL Storage</b><br/>Saves complete benchmark evidence")]
      ARTIFACT --> VALIDATE --> SANITIZE --> COST --> STORE
    end
    subgraph ANALYTICS["EVALUATION & REPORTING ───"]
      direction LR
      EVALUATE["<b>Evaluation</b><br/>Measures quality and failures"]
      REPORTING["<b>Reporting Service</b><br/>Aggregates runs and comparisons"]
      REPORTAPI["<b>FastAPI Reporting API</b><br/>Exposes read-only reports"]
      DASHBOARD["<b>Next.js Dashboard</b><br/>Presents decision-ready evidence"]
      OUTPUTS["<b>Charts · Tables · CSV · Excel</b><br/>Delivers reports and case evidence"]
      EVALUATE --> REPORTING --> REPORTAPI --> DASHBOARD --> OUTPUTS
    end

    EXECUTION --> ARTIFACT
    STORE --> EVALUATE
  end

  FINAL -. "measured outcome for controlled cases" .-> EXECUTION

  classDef runtime fill:#172033,stroke:#58a6ff,color:#f0f6fc,stroke-width:1.5px;
  classDef security fill:#2b2116,stroke:#d29922,color:#f0f6fc,stroke-width:1.5px;
  classDef data fill:#132a24,stroke:#3fb950,color:#f0f6fc,stroke-width:1.5px;
  classDef model fill:#211b33,stroke:#a371f7,color:#f0f6fc,stroke-width:1.5px;
  classDef benchmark fill:#20242b,stroke:#8b949e,color:#f0f6fc,stroke-width:1.2px;
  classDef decision fill:#2b2116,stroke:#d29922,color:#f0f6fc,stroke-width:2px;

  class CUSTOMER,API,MAPPER,SERVICE,CONTEXT,SELECTION,REGISTRY,CAPABILITY,RESULT,CONTINUE,FINAL runtime;
  class AUTHN,IDENTITY,PRIVIN,RESOLVER,BINDER,SCHEMA,ROLE,TOOLA,OWNER,GROUND,PRIVOUT,AUDIT security;
  class STATE,REPOSITORY,ORM,POSTGRES,EXECSTATE data;
  class PROVIDER1,QWEN1,PROVIDER2,QWEN2 model;
  class RUNNER,CASE,REAL,EXECUTION,ARTIFACT,VALIDATE,SANITIZE,COST,STORE,EVALUATE,REPORTING,REPORTAPI,DASHBOARD,OUTPUTS benchmark;
  class TOOLQ decision;

  style RUNTIME fill:#0d1117,stroke:#58a6ff,color:#f0f6fc,stroke-width:2px
  style ENTRY fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style INVOCATION fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style SECURE fill:#0d1117,stroke:#d29922,color:#e6edf3,stroke-width:1px
  style TRUST fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style ACCESS fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style BUSINESS fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style RESPONSE fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style INFRA fill:#0d1117,stroke:#8b949e,color:#e6edf3,stroke-width:1px
  style BENCHMARK fill:#0d1117,stroke:#8b949e,color:#f0f6fc,stroke-width:2px
  style CAMPAIGN fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style INGEST fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style ANALYTICS fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
```


## Architecture Component Guide

The architecture contains two separate systems. The **CX Harness Production
Runtime** serves customer requests. The **Benchmark & Evaluation Pipeline** sends
controlled test cases through that real runtime and analyzes the resulting
evidence; it does not replace or bypass production execution.

### Phase 1 — Request Entry

**Purpose:** Convert an external HTTP request into a trusted application request.

- **Customer Application:** Sends the message and conversation information.
- **FastAPI Endpoint:** Validates the public request and maps safe HTTP errors.
- **Authentication:** Verifies who made the request.
- **Trusted Identity:** Carries application-verified customer and role data.
- **API Mapper:** Converts the transport request into application input.
- **ModelPipelineService:** Starts the customer-support use case.

**Output:** A validated request with trusted identity, ready for model context
construction.

### Phase 2 — Model Invocation

**Purpose:** Build the model context and ask the configured model what should
happen next.

- **Data Protection:** Removes or masks sensitive input that is not required.
- **Context Builder:** Adds the production prompt, ordered history, and current
  customer message.
- **Provider Adapter:** Translates between harness contracts and Ollama, Gemini,
  or another provider protocol.
- **Model:** Returns either a final answer or one or more structured tool
  requests.

The **Tool requested?** decision sends tool requests into the secure execution
pipeline. A direct answer goes to final output protection.

### Phase 3 — Secure Tool Execution

**Purpose:** Turn an untrusted model proposal into one validated, authorized
business operation.

- **ToolSelection:** Normalizes the provider's requested call.
- **ToolRegistry:** Rejects unknown, disabled, duplicate, or ambiguous tools.
- **Conversation State:** Supplies remembered verified context; state is not
  authorization.
- **Entity Resolver:** Resolves references such as “that order” to a
  customer-scoped verified entity.
- **Trusted Argument Binder:** Replaces protected model arguments with trusted
  application values.
- **Schema Validation:** Validates the final bound arguments.
- **Role Policy:** Checks whether the caller's role may use the capability.
- **Tool Authorization:** Checks whether that role may invoke the exact tool.
- **Ownership Authorization:** Verifies access to the requested customer
  resource.
- **Business Capability:** Executes customer-support business rules.
- **Repository:** Encapsulates customer-scoped persistence queries.
- **SQLAlchemy:** Translates Python persistence operations into SQL.
- **PostgreSQL:** Stores the current business truth.

**Output:** A structured, customer-safe ToolResult or a safe failure.

### Phase 4 — Response Generation

**Purpose:** Give verified evidence back to the model and produce the final
customer-facing response.

- **ToolResult:** Represents structured success or business failure.
- **Grounding Policy:** Verifies that customer-specific claims have trusted
  transactional evidence.
- **Continuation Builder:** Adds ordered tool results to the working
  conversation.
- **Provider Adapter:** Translates the continuation into provider format.
- **Model:** Writes natural language using the verified evidence.
- **Data Protection:** Protects the final output before it leaves the service.
- **Customer Response:** Returns the safe answer to the caller.

The model writes language; it does not create the underlying order, delivery,
payment, or refund facts.

### Phase 5 — Runtime Infrastructure

**Purpose:** Keep every execution bounded, observable, isolated, and clean.

- **Orchestration:** Controls model turns and tool cycles.
- **Execution State:** Tracks completed work and prevents inconsistent reuse.
- **Cancellation & Timeouts:** Stop provider or tool work predictably.
- **Tracing & Logging:** Record a sanitized execution timeline and diagnostics.
- **Security Auditing:** Record security events without raw PII.
- **Cleanup:** Release request-scoped resources after every outcome.

These services are active across the runtime. They are support controls, not
additional sequential customer steps.

### Benchmark & Evaluation Pipeline

**Purpose:** Evaluate models through the real harness without changing runtime
behavior.

- **Benchmark Runner:** Coordinates models, cases, and repetitions.
- **Benchmark Case:** Defines one controlled, versioned customer scenario.
- **Real CX Harness Execution:** Enters the same production execution boundary.
- **Conversation Execution:** Captures measured provider turns, tools, usage,
  latency, outcome, and failures.
- **Artifact Creation:** Normalizes the evidence into provider-neutral
  contracts.
- **Validation:** Rejects incomplete or inconsistent evidence.
- **Sanitization:** Removes PII, secrets, and unsafe metadata.
- **Cost Calculation:** Applies the pricing snapshot saved with the run.
- **Atomic PostgreSQL Storage:** Saves a complete case or rolls it all back.
- **Evaluation:** Stores quality, grounding, tool, and failure signals.
- **Reporting Service:** Aggregates runs and performs compatible comparisons.
- **FastAPI Reporting API:** Exposes read-only reports and exports.
- **Next.js Dashboard:** Presents the stored evidence.
- **Charts, Tables, CSV, and Excel:** Deliver manager and engineering views.

## Architecture Phase Summary

| Area | Responsibility | Main input | Main output |
|---|---|---|---|
| Request Entry | Establish a trusted application request | HTTP request and credential | Validated request and trusted identity |
| Model Invocation | Ask the model for its next action | Protected conversation context | Final answer or tool selection |
| Secure Tool Execution | Validate and execute approved business work | Untrusted tool request | Structured ToolResult |
| Response Generation | Turn verified evidence into safe language | ToolResult and conversation | Grounded customer response |
| Runtime Infrastructure | Bound, observe, and clean execution | Runtime events | State, trace, audit, and cleanup |
| Benchmark Pipeline | Evaluate controlled executions | Versioned benchmark case | Stored evidence and reports |

## Example: “Where is my latest order?”

1. The customer application sends the message to the FastAPI endpoint.
2. Authentication creates the trusted customer identity.
3. The mapper and ModelPipelineService prepare the application request.
4. Data protection and Context Builder assemble the safe model context.
5. The provider asks the model what to do.
6. The model requests an approved current-orders tool.
7. ToolSelection and ToolRegistry normalize and identify the request.
8. Entity resolution and trusted binding ensure protected values come from the
   application, not the model.
9. Schema, role, tool, and ownership checks approve the bound request.
10. The business capability asks its repository for the authenticated
    customer's current orders.
11. SQLAlchemy queries PostgreSQL, the source of business truth.
12. A safe ToolResult returns through grounding and continuation.
13. The provider asks the model for the next turn.
14. The model writes a natural answer using verified order evidence.
15. Data protection checks the output before it returns to the customer.
16. Runtime state, tracing, auditing, timeouts, and cleanup protect the complete
    execution.
17. If this was a controlled benchmark case, its completed trace is normalized,
    validated, sanitized, stored, evaluated, and shown in the dashboard.

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

## Benchmark Dashboard Deployment

The production layout is:

```text
Browser → Render Next.js dashboard → Render FastAPI service → Render PostgreSQL
```

The dashboard is read-only with respect to benchmark reporting. It uses the
existing Stage 16 reporting endpoints and never fabricates benchmark data.
The Render backend uses the existing SQLAlchemy session layer and Alembic
migrations.

### Required environment variables

Configure secrets in Render, never in Git.

| Platform | Variable | Purpose |
|---|---|---|
| Render | `DATABASE_URL` | Existing Render PostgreSQL connection string |
| Render | `ENVIRONMENT=production` | Disables development debug behavior |
| Backend | `CORS_ALLOWED_ORIGINS` | Exact Render dashboard origin, normally `https://cx-harness-benchmark-dashboard.onrender.com` |
| Render | `AUTHENTICATION_HMAC_SECRET` | Existing authentication signing secret, at least 32 random characters |
| Render | `SECURITY_AUDIT_PSEUDONYM_KEY` | Separate security-audit pseudonym key |
| Frontend | `NEXT_PUBLIC_API_BASE_URL` | Render backend URL: `https://cx-harness-benchmark-api.onrender.com/api/v1` |
| Frontend | `NEXT_PUBLIC_API_TIMEOUT_MS` | Browser API timeout; default `30000` |

Ollama settings are not required for read-only benchmark reporting. Do not
expose a local Ollama endpoint publicly merely to serve the dashboard.

### Deploy both services with one Render Blueprint

The root `render.yaml` defines both web services. The backend uses `backend/` as
its root directory and runs:

```bash
# Build
pip install -r requirements.txt

# Non-destructive benchmark-only migration
python -m alembic -c alembic.ini upgrade b2aa96d282d0

# Start (Render supplies PORT)
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

In Render, create a Blueprint from this repository, set the required secret
variables, and point `DATABASE_URL` at the existing PostgreSQL database. The
health-check path is `/health`. If the selected Render plan does not support a
pre-deploy command, run the same benchmark-only Alembic upgrade command once from a Render
Shell before starting the new version. Never run downgrade, reset, drop, or
seed commands against production.

The frontend is a second Render Web Service rooted at `frontend/` and runs:

```bash
# Build
npm ci && npm run build

# Start (Render supplies PORT)
npm run start -- --hostname 0.0.0.0 --port $PORT
```

The Blueprint supplies the expected Render service URLs. If Render adds a suffix
because either service name is already taken, update `NEXT_PUBLIC_API_BASE_URL`
and `CORS_ALLOWED_ORIGINS` to the exact generated HTTPS origins, then redeploy
both services. Do not use localhost in production.

### Verify the deployment

1. Open `https://<render-service>/health` and confirm the response is
   `{"status":"ok","service":"cx-harness-api"}`.
2. Open `https://<render-service>/api/v1/benchmark-reporting/runs` and confirm
   stored benchmark runs are returned, or an explicit empty list if the
   database has no runs.
3. Open `https://<render-dashboard>/benchmark-reporting` and verify run listing,
   run detail, comparison, and Excel/CSV downloads.
4. Confirm browser requests use HTTPS and the Render API returns the exact
   Render dashboard origin in `Access-Control-Allow-Origin`.

Future updates deploy automatically from the connected Git branch. Apply only
forward, reviewed Alembic migrations and retain the existing PostgreSQL backup
and recovery policy.

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
