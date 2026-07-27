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

The complete provider-independent execution, tool, persistence, evaluation,
reporting, and presentation flow is rendered directly by GitHub:

```mermaid
%% CX Harness — complete master architecture flow (native GitHub dark mode)
%% Rendered assets live in docs/assets/architecture/.
%%{init: {"theme":"dark","flowchart":{"curve":"linear","nodeSpacing":45,"rankSpacing":65,"htmlLabels":true},"themeVariables":{"background":"#0d1117","primaryColor":"#222222","primaryTextColor":"#e6edf3","primaryBorderColor":"#c9d1d9","lineColor":"#c9d1d9","secondaryColor":"#222222","tertiaryColor":"#222222","clusterBkg":"#0d1117","clusterBorder":"#30363d","fontFamily":"Arial, sans-serif","fontSize":"16px"}}}%%
flowchart TB

  subgraph DATASET["1 · DATASET & CAMPAIGN"]
    direction TB
    DS["<b>Benchmark Dataset</b><br/>CX_Benchmark_100_Test_Cases.numbers<br/>100 customer cases"]
    DV["<b>Dataset Validation</b><br/>immutable source · 100 unique case IDs<br/>language and category validation"]
    CR["<b>Campaign Runner</b><br/>models × cases × repetitions<br/>concurrency and continuation policy"]
    CL["<b>Case Loader</b><br/>Case ID · Language · Category · Customer Message"]
    BC["<b>Single Benchmark Case</b><br/>one isolated customer execution"]
    DS --> DV --> CR --> CL --> BC
  end

  subgraph HARNESS["2 · PROVIDER-INDEPENDENT CX HARNESS"]
    direction TB
    EC["<b>ExecutionContext</b><br/>trace_id · execution_id · conversation_id<br/>trusted customer_id · principal_role · model_name"]
    SEC["<b>Identity & Security Boundary</b><br/>• Authentication + trusted identity<br/>• Role, tool, ownership + privacy policy"]
    CB["<b>ConversationContext + ContextBuilder</b><br/>immutable ordered messages<br/>trusted conversation identity"]
    PB["<b>ProductionSystemPromptBuilder</b><br/>Production System Prompt<br/>PromptManager → PromptPackage"]
    PA["<b>PromptAdapterRegistry</b><br/>provider-neutral prompt adapter boundary"]
    PR["<b>ProviderRegistry / ModelProvider</b><br/>provider-independent model contract<br/>capability metadata"]
    LOOP["<b>BoundedModelToolLoopService</b><br/>• Finite, deterministic provider turns<br/>• Timeout, cancellation + correlation"]
    REQ["<b>ModelToolLoopTurnRequest</b><br/>system instructions · working conversation<br/>tool definitions · prior tool outcomes"]
    EC --> SEC --> CB --> PB --> PA --> PR --> LOOP --> REQ
  end

  subgraph PROVIDERS["3 · PROVIDERS & MODEL SELECTION"]
    direction TB
    MS{"<b>Model Selection</b>"}
    QW["<b>Qwen 3 8B</b><br/>OllamaQwenProvider<br/>Agent Mode · native tool calling"]
    F9["<b>Fanar 9B</b><br/>local Ollama deployment<br/>Chat Mode · tools unavailable"]
    FI["<b>Fanar 9B Instruct</b><br/>local Ollama deployment<br/>Chat Mode · tools unavailable"]
    FM["<b>Future Models</b><br/>ModelProviderAdapter<br/>registered without orchestrator branching"]
    MRQ["<b>Provider Request</b><br/>local Ollama /api/chat<br/>configured context · output cap · timeout"]
    MRS["<b>ModelToolLoopTurnResponse</b><br/>• Final response<br/>• Or ordered tool calls"]
    MS --> QW --> MRQ
    MS --> F9 --> MRQ
    MS --> FI --> MRQ
    MS --> FM --> MRQ
    MRQ --> MRS
  end

  subgraph TOOLING["4 · TOOL SELECTION, TRUSTED BINDING & EXECUTION"]
    direction TB
    TCD["<b>Provider Tool-Call Detection</b><br/>Ollama native tool_calls → ToolSelectionRequest"]
    NEED{"<b>Executable tool call?</b>"}
    DIRECT["<b>No — Final Model Response</b><br/>validated provider-neutral ModelResponse"]
    TS["<b>ToolSelectionService</b><br/>ProviderToolCallAdapterRegistry<br/>ordered neutral selections"]
    TR["<b>ToolRegistry</b><br/>metadata · enabled tools · versions<br/>duplicate/unknown protection"]
    BIND["<b>TrustedSelectionPipeline</b><br/>• TrustedArgumentBinder + OrderEntityResolver<br/>• Provider identifiers never become authority"]
    SCHEMA["<b>ToolSelectionResolver</b><br/>Pydantic tool-schema validation<br/>validated bound arguments only"]
    AUTH["<b>Authorization & Policy Checks</b><br/>• Role + tool authorization<br/>• Ownership + privacy protection"]
    TG["<b>SingleToolExecutionGateway</b><br/>ToolExecutor / WriteFrameworkExecutor<br/>exactly one validated invocation"]

    subgraph TOOLS["Registered Business Capabilities"]
      direction LR
      CT["<b>Customer</b><br/>get_customer_profile<br/>get_customer_summary"]
      OT["<b>Orders</b><br/>• Status, current + detail<br/>• History + items"]
      DT["<b>Delivery</b><br/>• Status, ETA + window<br/>• Latest event + history"]
      PT["<b>Payments & Refunds</b><br/>• Status, method, summary + history<br/>• Refund lifecycle + eligibility"]
      KT["<b>Knowledge</b><br/>• Search, policy + FAQ<br/>• Related approved articles"]
      WT["<b>Controlled Writes</b><br/>• Cancel, address, refund + support<br/>• Transaction + idempotency framework"]
    end

    TCD --> NEED
    NEED -- "No" --> DIRECT
    NEED -- "Yes" --> TS --> TR --> BIND --> SCHEMA --> AUTH --> TG
    TG --> CT
    TG --> OT
    TG --> DT
    TG --> PT
    TG --> KT
    TG --> WT
  end

  subgraph REPOSITORIES["5 · REPOSITORY BOUNDARY"]
    direction TB
    RP["<b>SQLAlchemy Repository Layer</b><br/>business tools never issue raw SQL"]
    R1["<b>Business Repositories</b><br/>• Customer, Order, Item + Delivery<br/>• Payment, Refund + Knowledge"]
    R2["<b>Execution Repositories</b><br/>• Conversation, Message + ToolCall<br/>• ModelRun + Evaluation"]
    RP --> R1
    RP --> R2
  end

  subgraph DATABASE["6 · POSTGRESQL — TRUSTED BUSINESS & EXECUTION DATA"]
    direction TB
    DB[("<b>PostgreSQL</b><br/>SQLAlchemy sessions · Alembic-managed schema")]

    subgraph TABLES["Core Tables & Representative Customer-Safe Fields"]
      direction LR
      CUST["<b>customers</b><br/>id · first_name · phone<br/>preferred_language"]
      ORD["<b>orders</b><br/>id · order_number · status<br/>payment_status · total_amount"]
      ITEM["<b>order_items</b><br/>order_id · product_name<br/>quantity · unit_price"]
      CONV["<b>conversations</b><br/>customer_id · status · channel<br/>active_model"]
      MSG["<b>messages</b><br/>role · content<br/>sequence_number"]
      MRUN["<b>model_runs</b><br/>provider · model · status<br/>latency · prompt/completion tokens"]
      TCALL["<b>tool_calls</b><br/>tool_name · version · status<br/>sanitized arguments/result · duration"]
      EVAL["<b>evaluations</b><br/>passed · intent/tool scores · overall_score<br/>details_json: grounding/hallucination evidence"]
    end

    CUST -- "1 : many" --> ORD
    CUST -- "1 : many" --> CONV
    ORD -- "1 : many" --> ITEM
    ORD -. "logical order context in sanitized payload; no direct FK" .-> TCALL
    CONV -- "1 : many" --> MSG
    CONV -- "1 : many" --> MRUN
    MRUN -- "1 : many" --> TCALL
    MRUN -- "1 : many" --> EVAL
    DB --> CUST
    DB --> ORD
    DB --> ITEM
    DB --> CONV
    DB --> MSG
    DB --> MRUN
    DB --> TCALL
    DB --> EVAL
  end

  subgraph CONTINUATION["7 · GROUNDED CONTINUATION & TERMINATION"]
    direction TB
    TRES["<b>ToolResult → ToolExecutionOutcome</b><br/>structured success or business failure<br/>sanitized customer-safe payload"]
    GR["<b>BusinessGroundingPolicy</b><br/>capability-based transactional evidence<br/>policy evidence remains separate"]
    TCYCLE["<b>ToolContinuationCycle</b><br/>ProviderContinuationAdapterRegistry<br/>correlated call ID · ordered results"]
    BACK["<b>Model Receives Tool Result</b><br/>working conversation updated<br/>next bounded provider turn"]
    REPEAT["<b>↺ Continue Tool Loop</b><br/>Additional calls return to Stage 4<br/>within the same bounded execution"]
    FINAL["<b>Final Model Response</b><br/>grounded, validated, customer-safe"]
    TRACE["<b>OrchestrationExecutionTrace</b><br/>provider turns · tool executions · timeline<br/>latency · diagnostic summary · correlation"]
    TERM["<b>Termination & Safety Policies</b><br/>• Final, bounded, failure + timeout outcomes<br/>• Grounding requirement + cleanup"]
    TRES --> GR --> TCYCLE --> BACK
    BACK -. "additional tool call" .-> REPEAT
    BACK -- "terminal answer" --> FINAL
    DIRECT --> FINAL
    FINAL --> TRACE --> TERM
  end

  subgraph INGESTION["8 · NORMALIZED BENCHMARK INGESTION — STAGE 16.2"]
    direction TB
    ART["<b>CompletedConversationExecution</b><br/>• Provider + tool execution artifacts<br/>• Termination + deterministic evaluation"]
    VS["<b>Validation & Sanitization</b><br/>immutable contracts · contiguous ordering<br/>PII/secret protection · deterministic costing"]
    BIS["<b>BenchmarkIngestionService</b><br/>create/start run · atomic case ingestion<br/>idempotency · conflict detection · finalize"]
    BAR["<b>Benchmark Analytics Repositories</b><br/>Suite · Run · ConversationResult · Turn<br/>ToolExecution · Metric · Failure repositories"]
    BP[("<b>Persist Benchmark Result</b><br/>• Suites, runs, conversations + turns<br/>• Tools, metrics + failure events")]
    ART --> VS --> BIS --> BAR --> BP
  end

  subgraph EVALUATION["9 · DETERMINISTIC EVALUATION & ANALYTICS"]
    direction TB
    EE["<b>Evaluation Evidence</b><br/>stored deterministic metrics and failure signals<br/>no recalculation during presentation"]
    EM1["Intent Accuracy · Grounding · Hallucination<br/>Tool Selection · Argument Validation · Tool Success"]
    EM2["Business/Task Completion · Authorization<br/>Latency · Token Usage · Cost<br/>Failure Category & Responsibility"]
    EE --> EM1
    EE --> EM2
  end

  subgraph REPORTING["10 · REPORTING ENGINE — STAGE 16.3"]
    direction TB
    BRR["<b>BenchmarkReportingRepository</b><br/>read-only complete analytics snapshot"]
    BRS["<b>BenchmarkReportingService</b><br/>deterministic aggregation<br/>ScoringPolicy + compatibility checks"]
    RS1["Run Summary · Language Performance<br/>Category Performance · Failure Analysis"]
    RS2["Latency Analysis · Token Analysis<br/>Cost Analysis · Tool Performance<br/>Model Comparison + Winner Explanation"]
    BRR --> BRS
    BRS --> RS1
    BRS --> RS2
  end

  subgraph PRESENTATION["11 · PRESENTATION & EXPORT — STAGE 16.4"]
    direction TB
    BPS["<b>BenchmarkPresentationService</b><br/>report discovery · case evidence<br/>read-only presentation facade"]
    API["<b>FastAPI Reporting Routes</b><br/>run list · run detail · comparison<br/>Excel and CSV download endpoints"]
    UI["<b>Next.js Benchmark Dashboard</b><br/>• Executive KPIs, charts + comparison<br/>• Evidence table, case viewer + filters"]
    EX["<b>Presentation Exports</b><br/>ExcelExporter · native charts · wrapped evidence<br/>CsvZipExporter · deterministic CSV tables"]
    REPORT["<b>Manager-Ready Benchmark Report</b><br/>evidence · metrics · limitations<br/>winner explanations · downloadable artifacts"]
    BPS --> API
    API --> UI
    API --> EX
    UI --> REPORT
    EX --> REPORT
  end

  BC --> EC
  REQ --> MS
  MRS --> TCD
  CT --> RP
  OT --> RP
  DT --> RP
  PT --> RP
  KT --> RP
  WT --> RP
  R1 --> DB
  R2 --> DB
  DB --> TRES
  TERM --> ART
  BP --> EE
  EM1 --> BRR
  EM2 --> BRR
  RS1 --> BPS
  RS2 --> BPS

  classDef normal fill:#222222,stroke:#c9d1d9,color:#e6edf3,stroke-width:1px;
  class DS,DV,CR,CL,BC,EC,SEC,CB,PB,PA,PR,LOOP,REQ,TCD,DIRECT,TS,TR,BIND,SCHEMA,AUTH,TG,CT,OT,DT,PT,KT,WT,RP,R1,R2,DB,CUST,ORD,ITEM,CONV,MSG,MRUN,TCALL,EVAL,TRES,GR,TCYCLE,BACK,REPEAT,FINAL,TRACE,TERM,ART,VS,BIS,BAR,BP,EE,EM1,EM2,BRR,BRS,RS1,RS2,BPS,API,UI,EX,REPORT,NEED,MS,QW,F9,FI,FM,MRQ,MRS normal;

  style DATASET fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style HARNESS fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style PROVIDERS fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style TOOLING fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style TOOLS fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style REPOSITORIES fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style DATABASE fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style TABLES fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style CONTINUATION fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style INGESTION fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style EVALUATION fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style REPORTING fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
  style PRESENTATION fill:#0d1117,stroke:#30363d,color:#e6edf3,stroke-width:1px
```


## Architecture Component Guide

This guide explains the diagram for readers who are new to the project. A
**provider** is an adapter to a model service such as Ollama. An
**orchestrator** coordinates model turns, tool use, limits, and cleanup without
containing provider-specific or business logic. A **model turn** is one request
to a model and its response. A **tool call** is a structured request from the
model to run an approved business capability. A **conversation execution** is
the full lifecycle of one customer request, including all model turns and tool
calls.

The diagram contains two related paths. Live traffic enters through the FastAPI
model-invocation route and joins the runtime described in Stages 2–7. Stage 1
and Stages 8–11 are benchmark and reporting workflows. They execute or ingest
measured conversations, but they do not participate in model reasoning during a
normal customer request.

### Stage 1 — Dataset and Campaign

**Purpose:**
This benchmark-only stage converts the fixed dataset into isolated cases that
can be run consistently. It exists so every model sees the same questions,
languages, categories, and expected behavior.

**Input:**
The approved benchmark dataset, selected models, repetitions, and campaign
settings.

**Output:**
One validated Single Benchmark Case ready for the harness.

#### Benchmark Dataset

- **What it is and does:** The source file containing the 100 approved customer
  cases.
- **Why it is needed:** Keeping it unchanged makes model comparisons
  reproducible.
- **Receives:** Curated IDs, messages, languages, categories, and expectations.
- **Returns:** The complete case collection for Dataset Validation.

#### Dataset Validation

- **What it is and does:** Checks required fields, unique IDs, languages, and
  categories before execution.
- **Why it is needed:** Bad source data must not create misleading benchmark
  results.
- **Receives:** The Benchmark Dataset.
- **Returns:** A valid immutable case collection or a clear validation error.

#### Campaign Runner

- **What it is and does:** Coordinates benchmark models, cases, repetitions,
  concurrency, and continuation.
- **Why it is needed:** It runs campaigns consistently and continues recording
  failed cases. It is not the live customer orchestrator.
- **Receives:** Validated cases and campaign configuration.
- **Returns:** Ordered case executions and their completion records.

#### Case Loader

- **What it is and does:** Converts one source row into the benchmark execution
  format.
- **Why it is needed:** Spreadsheet details remain outside the runtime.
- **Receives:** Case ID, language, category, and customer message.
- **Returns:** One normalized case definition.

#### Single Benchmark Case

- **What it is and does:** Represents one isolated customer execution.
- **Why it is needed:** State, failures, and timings from one case must not leak
  into another.
- **Receives:** A normalized case definition.
- **Returns:** A message and benchmark identity for Stage 2.

**Connection to Stage 2:**
The benchmark case enters the same provider-independent harness used for model
execution. Live traffic instead enters through POST /api/v1/model/invoke and
ModelPipelineService before joining that runtime.

### Stage 2 — Provider-Independent CX Harness

**Purpose:**
This stage establishes trusted context and runs the bounded orchestration
service. **Runtime composition** means constructing registries, providers,
security services, repositories, and orchestration objects and injecting them
into each other. build_model_tool_loop performs this composition without making
a network request during construction.

**Input:**
A customer message, conversation ID, application-authenticated identity,
history, system instructions, and provider/model configuration.

**Output:**
A ModelToolLoopTurnRequest for the selected provider.

#### API or Request Entry Point

- **What it is and does:** The live entry is POST /api/v1/model/invoke. Its
  FastAPI route validates ModelInvocationRequest and maps safe errors to HTTP.
- **Why it is needed:** Transport validation stays separate from runtime logic.
- **Receives:** A public request and TrustedCustomerIdentity supplied by an
  application authentication dependency.
- **Returns:** One ModelPipelineService invocation.

#### ModelPipelineService

- **What it is and does:** The application boundary that protects text, builds
  context, obtains the configured pipeline lazily, invokes it once, and maps the
  result.
- **Why it is needed:** API, CLI, tests, and future entry points can share one
  safe application contract.
- **Receives:** Conversation ID, message, history, system instructions, and
  TrustedCustomerIdentity.
- **Returns:** Safe content, provider name, and model name.

#### ExecutionContext

- **What it is and does:** An **execution context** is immutable metadata for
  one run: trace, execution, and conversation IDs plus trusted customer ID,
  role, and model.
- **Why it is needed:** Downstream code must not trust identity generated by the
  model.
- **Receives:** Values established by the application and authentication layer.
- **Returns:** Trusted correlation and identity data for authorization, tools,
  persistence, and tracing.

#### Identity & Security Boundary

- **What it is and does:** Applies authentication, role policy, tool
  authorization, ownership checks, privacy protection, and security auditing.
- **Why it is needed:** A **trusted identity** must come from the application,
  never from a prompt or provider argument.
- **Receives:** Authenticated identity, requested capability/resource, and data.
- **Returns:** Permission and protected data, or a safe structured failure.

#### ConversationContext + ContextBuilder

- **What it is and does:** ConversationContext is the immutable ordered
  conversation; ContextBuilder validates and normalizes it.
- **Why it is needed:** All providers receive the same stable conversation
  meaning without mutating caller-owned input.
- **Receives:** Protected instructions, history, current message, provider, and
  model.
- **Returns:** A valid ConversationContext.

#### ProductionSystemPromptBuilder

- **What it is and does:** Builds centralized, versioned customer-support
  instructions.
- **Why it is needed:** Every request uses the same language, safety, grounding,
  and tool-use guidance.
- **Receives:** Protected supplemental system instructions.
- **Returns:** Final instructions for PromptManager.

#### PromptManager → PromptPackage

- **What it is and does:** Converts ConversationContext into the
  provider-neutral PromptPackage.
- **Why it is needed:** Conversation meaning remains independent of Ollama
  formatting.
- **Receives:** Valid ConversationContext.
- **Returns:** Immutable ordered prompt messages and instructions.

#### PromptAdapterRegistry

- **What it is and does:** Selects the registered prompt translator for a
  provider.
- **Why it is needed:** The harness avoids provider-specific branches.
- **Receives:** Provider name and PromptPackage.
- **Returns:** A translated provider request representation.

#### ProviderRegistry / ModelProvider

- **What it is and does:** ProviderRegistry catalogues configured ModelProvider
  implementations; ModelProvider is their common invocation contract.
- **Why it is needed:** Providers can be exchanged without changing the
  orchestrator.
- **Receives:** Explicit registrations and a normalized provider name.
- **Returns:** The selected provider through a neutral interface.

#### BoundedModelToolLoopService

- **What it is and does:** The central **orchestrator** and iteration service.
  It runs finite model turns, coordinates tools, enforces limits, propagates
  cancellation, prevents duplicates, and cleans run-local state.
- **Why it is needed:** Model/tool execution must be bounded and deterministic.
- **Receives:** ConversationContext, ExecutionContext, provider/model identity,
  optional cancellation, and trusted customer message.
- **Returns:** ModelToolLoopResult with a final response or structured
  termination.

#### ModelToolLoopTurnRequest

- **What it is and does:** The immutable input for one model turn, including
  conversation, tool definitions, prior outcomes, call history, and turn number.
- **Why it is needed:** Every provider consumes one stable turn contract.
- **Receives:** Current orchestrator state.
- **Returns:** A provider-neutral request for Stage 3.

**Connection to Stage 3:**
ProviderRegistry resolves the configured provider. Only that provider builds
its transport payload.

### Stage 3 — Providers and Model Selection

**Purpose:**
This stage isolates model transport and response parsing. Model reasoning occurs
inside the selected model; identity, authorization, binding, persistence, and
evaluation remain deterministic application logic.

**Input:** ModelToolLoopTurnRequest and provider/model names.
**Output:** ModelToolLoopTurnResponse containing final text or ordered tool
calls.

#### Model Selection

- **What/why:** Resolves the provider/model from ProviderRegistry without
  provider-specific branches in orchestration.
- **Receives/returns:** Receives normalized names and returns one registered
  provider implementation.

#### Qwen 3 8B / OllamaQwenProvider

- **What/why:** The local Ollama adapter for Qwen in Agent Mode. It translates
  messages and tools, applies Ollama settings, and validates responses.
- **Receives/returns:** Receives ModelToolLoopTurnRequest and tool definitions;
  returns normalized text or native tool calls with preserved IDs and order.

#### Fanar 9B and Fanar 9B Instruct

- **What/why:** Local Ollama models represented in Chat Mode because the current
  deployments do not provide the native tool-calling behavior used by the agent
  loop.
- **Receives/returns:** Receive normal chat content and return text. Tool
  metrics are unavailable for these Chat Mode runs.

#### Future Models / ModelProviderAdapter

- **What/why:** The extension point for new providers using the same contract,
  so orchestration does not change.
- **Receives/returns:** Receives neutral requests and returns neutral responses.

#### Provider Request

- **What/why:** The model-specific payload built only inside the provider
  boundary. For Ollama it targets local /api/chat with messages, tools, context
  size, output cap, timeout, and keep-alive settings.
- **Receives/returns:** Receives normalized turn data and returns one transport
  request.

#### ModelToolLoopTurnResponse

- **What/why:** The normalized result of one **model turn**. It contains either
  final assistant text or ordered tool calls, avoiding ambiguous state.
- **Receives/returns:** Receives a validated provider response and returns final
  content or selections for Stage 4.

**Connection to Stage 4:**
Provider Tool-Call Detection chooses the direct-answer path or the mandatory
trusted tool path.

### Stage 4 — Tool Selection, Trusted Binding, and Execution

**Purpose:**
This stage converts model suggestions into validated and authorized business
operations. The model may request a tool, but deterministic code decides whether
it is known, trusted, permitted, and executable.

**Input:** ModelToolLoopTurnResponse, ExecutionContext, ConversationState, and
ToolRegistry metadata.
**Output:** A direct answer, safe failure, or structured ToolResult.

#### Provider Tool-Call Detection and Executable tool call?

- **What/why:** Detection converts native calls to ToolSelectionRequest. The
  decision diamond separates final text from executable calls.
- **Receives/returns:** Receives ModelToolLoopTurnResponse and returns ordered
  selections or the No — Final Model Response path.

#### No — Final Model Response

- **What/why:** The provider-neutral answer used when no business tool is needed
  and grounding rules permit a direct response.
- **Receives/returns:** Receives final model content and returns ModelResponse to
  Stage 7.

#### ToolSelectionService

- **What/why:** Coordinates provider-neutral translation through
  ProviderToolCallAdapterRegistry while preserving IDs, versions, arguments,
  and order.
- **Receives/returns:** Receives provider call data and returns ordered
  ToolSelectionRequest objects.

#### ToolRegistry

- **What/why:** The central catalogue of approved tools. It records metadata,
  schema, version, capability, and enabled state and rejects duplicates or
  unknown tools.
- **Receives/returns:** Receives explicit startup registrations and lookup names;
  returns immutable definitions or a registered tool class.

#### TrustedSelectionPipeline

- **What/why:** The mandatory boundary that performs trusted binding before
  schema validation. Original provider identifiers are discarded after binding.
- **Receives/returns:** Receives ToolSelectionRequest, trusted execution values,
  conversation state, and trusted message; returns a bound validated selection
  or fail-closed failure.

#### TrustedArgumentBinder

- **What/why:** **Argument binding** injects or replaces protected arguments
  from trusted runtime values and verified entity resolution. Model-supplied
  customer/order identity never becomes authority.
- **Receives/returns:** Receives selection, policy, TrustedExecutionValues, and
  verified resolution; returns BoundToolSelectionRequest or safe failure.

#### OrderEntityResolver

- **What/why:** The sole trusted source of resolved order identity. It verifies
  explicit or state-derived references through a customer-scoped repository.
- **Receives/returns:** Receives authenticated customer scope and an order
  candidate; returns verified EntityResolutionResult or clarification,
  forbidden, not-found, stale, or invalid outcome.

#### ConversationState

- **What/why:** Immutable revisioned continuity across turns. It is context, not
  authorization, so every protected reference still requires verification.
- **Receives/returns:** Receives verified entities/tool outcomes and returns
  focus/candidates, never a directly executable protected ID.

#### ToolSelectionResolver

- **What/why:** Resolves tool version and validates bound arguments against the
  Pydantic input schema after binding.
- **Receives/returns:** Receives BoundToolSelectionRequest and ToolRegistry;
  returns ValidatedToolSelection or structured validation failure.

#### Authorization & Policy Checks

- **What/why:** Applies role policy, tool permission, ownership, and privacy
  checks using application identity rather than model claims.
- **Receives/returns:** Receives trusted identity, metadata, and bound arguments;
  returns permission or denial before execution.

#### SingleToolExecutionGateway

- **What/why:** The only execution path into ToolExecutor or
  WriteFrameworkExecutor, guaranteeing one validated invocation.
- **Receives/returns:** Receives validated, authorized, bound selection and
  ExecutionContext; returns ToolExecutionOutcome.

#### Customer

- **What/why:** get_customer_profile and get_customer_summary expose minimized
  customer-safe data.
- **Receives/returns:** Receives trusted customer scope and returns structured
  customer information or business failure.

#### Orders

- **What/why:** Status, current-order, detail, history, and item tools answer
  transactional questions from PostgreSQL rather than model memory.
- **Receives/returns:** Receives customer scope and verified order when needed;
  returns customer-safe order data or failure.

#### Delivery

- **What/why:** Provides status, ETA, window, latest event, and history.
- **Receives/returns:** Receives verified customer/order scope and returns
  trusted delivery facts or availability failure.

#### Payments & Refunds

- **What/why:** Provides status, method, summary, history, events, and
  eligibility without processor secrets.
- **Receives/returns:** Receives verified scope and returns customer-safe
  financial facts or business outcomes.

#### Knowledge

- **What/why:** Provides approved search, policy, FAQ, and related articles.
  Policy evidence cannot prove customer-specific transactional state.
- **Receives/returns:** Receives a knowledge query and returns published active
  content.

#### Controlled Writes

- **What/why:** cancel_order, update_delivery_address, initiate_refund, and
  create_support_ticket use WriteFrameworkExecutor, transactions, and
  idempotency.
- **Receives/returns:** Receive trusted validated authorized arguments and
  return WriteResult; success commits and failure rolls back.

**Connection to Stage 5:**
Tools call repositories instead of raw SQL. Repositories read or change the
trusted database inside the established transaction boundary.

### Stage 5 — Repository Boundary

**Purpose:**
A **repository** hides database queries behind domain operations. This keeps
SQLAlchemy and persistence rules out of business tools.

**Input:** Validated domain queries or commands.
**Output:** Domain records, controlled absence results, or managed updates.

#### SQLAlchemy Repository Layer

- **What/why:** Owns query construction and session use so tools contain no raw
  SQL.
- **Receives/returns:** Receives scoped parameters/changes and returns domain
  data or controlled persistence failure.

#### Business Repositories

- **What/why:** CustomerRepository, OrderRepository, OrderItemRepository,
  DeliveryRepository, PaymentRepository, RefundRepository, and
  KnowledgeRepository implement domain persistence.
- **Receives/returns:** Receive trusted IDs and criteria; return entities or safe
  empty/not-found outcomes.

#### Execution Repositories

- **What/why:** ConversationRepository, MessageRepository,
  ToolCallRepository/ToolCallAuditRepository,
  ModelRunRepository/ModelRunAuditRepository, and EvaluationRepository keep
  execution evidence separate from business records.
- **Receives/returns:** Receive sanitized execution records and return persisted
  records or operational read models.

**Connection to Stage 6:**
Repositories use SQLAlchemy sessions against the Alembic-managed PostgreSQL
schema.

### Stage 6 — PostgreSQL: Trusted Business and Execution Data

**Purpose:**
PostgreSQL is the durable source of truth for business state and execution
records. Foreign keys preserve ownership and lifecycle relationships.

**Input:** Repository queries and sanitized persistence records.
**Output:** Trusted business facts and durable execution evidence.

#### PostgreSQL

- **What/why:** The relational store providing constraints, transactions, and
  consistent reads through SQLAlchemy sessions.
- **Receives/returns:** Receives repository operations and returns rows or
  committed transaction outcomes.

#### customers, orders, and order_items

- **What/why:** customers stores profile/language; orders stores public number,
  status, payment status, total, and ownership; order_items stores products,
  quantities, and prices. Sensitive fields are minimized before exposure.
- **Receives/returns:** Receive business records and return customer-scoped
  profile, order, and item data.

#### conversations and messages

- **What/why:** conversations stores customer, status, channel, and active model;
  messages stores ordered role/content using sequence_number.
- **Receives/returns:** Receive sanitized lifecycle/message records and return
  conversation scope/history.

#### model_runs

- **What/why:** Stores provider/model, status, timestamps, latency, and token
  counts for each invocation.
- **Receives/returns:** Receives model lifecycle metadata and returns auditable
  model-run evidence.

#### tool_calls

- **What/why:** Stores tool/version, status, sanitized arguments/results,
  duration, and correlation without unrestricted sensitive payloads.
- **Receives/returns:** Receives ToolExecutor audit events and returns execution
  evidence.

#### evaluations

- **What/why:** Stores pass status, intent/tool scores, overall score, and
  grounding/hallucination evidence.
- **Receives/returns:** Receives structured evaluation and returns durable
  reporting evidence.

#### Database relationships

- **What/why:** Customers own orders/conversations; orders own items;
  conversations own messages/model runs; model runs own tool calls/evaluations.
  Order context in tool_calls is logical sanitized payload context, not a direct
  order foreign key.
- **Receives/returns:** Receives related records and returns referential
  integrity.

**Connection to Stage 7:**
Repository data becomes ToolResult and ToolExecutionOutcome. Grounding and
continuation decide how the model may use it.

### Stage 7 — Grounded Continuation and Termination

**Purpose:**
This stage returns tool evidence to the model and ends execution predictably.
**Grounding** means customer-specific claims are supported by verified tool
results instead of guesses. A **termination policy** defines why the bounded
loop stops.

**Input:** Tool outcomes or direct final content plus run-local state.
**Output:** Safe final response, structured termination, and trace.

#### ToolResult → ToolExecutionOutcome

- **What/why:** Normalizes tool success, business failure, and technical error
  into one provider-independent result.
- **Receives/returns:** Receives ToolResult or WriteResult and returns sanitized
  ToolExecutionOutcome with call identity.

#### BusinessGroundingPolicy

- **What/why:** Checks capability-based transactional evidence and keeps policy
  evidence separate, without hard-coded business tool names.
- **Receives/returns:** Receives message classification, tool metadata, and
  outcomes; returns permission to answer or safe grounding failure.

#### ToolContinuationCycle and ProviderContinuationAdapterRegistry

- **What/why:** ToolContinuationCycle connects ordered calls, outcomes, and
  continuation payloads. The registry selects provider-specific result
  translation without changing orchestration.
- **Receives/returns:** Receive selections/outcomes/provider name and return
  ProviderContinuationPayload values.

#### Model Receives Tool Result and Continue Tool Loop

- **What/why:** Adds tool-call and result messages to the working conversation.
  If another tool is requested, control returns to Stage 4 with ordering and
  duplicate protection intact.
- **Receives/returns:** Receives continuation data and returns updated context
  or another protected tool cycle.

#### Final Model Response

- **What/why:** The normalized, grounded, validated, privacy-protected customer
  answer.
- **Receives/returns:** Receives terminal assistant content/evidence and returns
  safe ModelResponse.

#### OrchestrationExecutionTrace

- **What/why:** A **trace** is a chronological diagnostic record of provider
  turns, tool executions, durations, failures, termination, and cleanup without
  raw secrets.
- **Receives/returns:** Receives loop events and returns an immutable trace and
  diagnostic summary.

#### Termination & Safety Policies

- **What/why:** Defines final, maximum-turn, invalid-call, business-failure,
  timeout, cancellation, provider-error, grounding, and cleanup outcomes.
- **Receives/returns:** Receives state, time, turn count, errors, and grounding
  decision; returns structured ModelToolLoopResult and termination metadata.

**Connection to Stage 8:**
Live execution returns its response here. Benchmark execution separately
normalizes evidence into artifacts for Stage 16.2 ingestion.

### Stage 8 — Normalized Benchmark Ingestion (Stage 16.2)

**Purpose:**
This benchmark-only stage validates and stores completed execution evidence. An
**artifact** is an immutable structured record. **Ingestion** is its controlled
validation and persistence. **Atomic persistence** commits all rows for a case
together or rolls them all back.

**Input:** Completed conversation, provider turns, tool executions,
termination, and evaluation evidence.
**Output:** Idempotently persisted analytics records.

#### CompletedConversationExecution

- **What/why:** The top-level artifact grouping one benchmark conversation and
  all its evidence.
- **Receives/returns:** Receives completed runtime evidence and returns one
  immutable ingestion request.

#### ProviderTurnExecution

- **What/why:** Records each provider turn's ordering, response type, tokens,
  latency, and safe failure information.
- **Receives/returns:** Receives normalized turn evidence and returns ordered
  turn records.

#### ToolExecutionArtifact

- **What/why:** Records each requested/executed tool with call ID, identity,
  status, duration, and sanitized evidence.
- **Receives/returns:** Receives tool outcomes and returns tool-execution
  records.

#### RuntimeTerminationArtifact

- **What/why:** Captures the stable reason and completion state at execution end.
- **Receives/returns:** Receives ModelToolLoopResult termination data and returns
  completion/failure evidence.

#### DeterministicEvaluationArtifact

- **What/why:** Stores metrics and failure signals produced by deterministic
  application rules. **Evaluation** compares expected behavior with evidence;
  the model does not grade itself.
- **Receives/returns:** Receives expectations and normalized execution and
  returns metrics/failures.

#### Validation & Sanitization

- **What/why:** Checks immutable contracts, ordering, identities, payload
  limits, and privacy. It also performs deterministic cost mapping from token
  use and configured prices.
- **Receives/returns:** Receives CompletedConversationExecution and returns
  storage-safe artifacts or rejection without partial writes.

#### BenchmarkIngestionService

- **What/why:** Coordinates suite/run lifecycle, idempotency, conflict
  detection, atomic case ingestion, and finalization.
- **Receives/returns:** Receives valid artifacts and returns created/confirmed
  records and run status.

#### Benchmark Analytics Repositories

- **What/why:** Suite, Run, ConversationResult, Turn, ToolExecution, Metric, and
  Failure repositories isolate analytics persistence.
- **Receives/returns:** Receive storage commands/read queries and return
  analytics entities or snapshots.

#### Persist Benchmark Result

- **What/why:** The benchmark suites, runs, conversations, provider turns, tool
  executions, metrics, and failure tables.
- **Receives/returns:** Receives atomic repository writes and returns durable
  evidence for Stage 9.

**Connection to Stage 9:**
Analytics reads stored metrics and failure evidence. Presentation does not
silently recalculate them.

### Stage 9 — Deterministic Evaluation and Analytics

**Purpose:**
This stage organizes evidence into comparable quality, safety, performance, and
cost measures. It is deterministic application logic, not model reasoning.

**Input:** Persisted cases, turns, tools, metrics, and failures.
**Output:** Evaluation evidence ready for reporting.

#### Evaluation Evidence

- **What/why:** The stored source of truth for scores and failure signals so
  reports remain reproducible.
- **Receives/returns:** Receives DeterministicEvaluationArtifact records and
  returns stable metrics.

#### Intent Accuracy · Grounding · Hallucination · Tool Selection · Argument Validation · Tool Success

- **What/why:** Measures understanding, supporting evidence, unsupported claims,
  correct tool choice, valid arguments, and execution success.
- **Receives/returns:** Receives expected behavior and execution evidence and
  returns criterion scores/failures.

#### Business/Task Completion · Authorization · Latency · Token Usage · Cost · Failure Category & Responsibility

- **What/why:** Measures outcome, security, efficiency, and cost. Failure
  classification assigns a stable cause/layer so a provider timeout is not
  mislabeled as wrong tool selection.
- **Receives/returns:** Receives termination, trace, token, timing, cost, and
  task evidence; returns metrics and categorized failures.

**Connection to Stage 10:**
BenchmarkReportingRepository loads a complete analytics snapshot for
deterministic aggregation.

### Stage 10 — Reporting Engine (Stage 16.3)

**Purpose:**
This read-only stage aggregates stored evidence into run summaries and model
comparisons. It does not execute models, tools, or evaluation.

**Input:** Compatible runs and persisted metrics.
**Output:** Reporting contracts for summaries and comparisons.

#### BenchmarkReportingRepository

- **What/why:** Loads a complete read-only analytics snapshot.
- **Receives/returns:** Receives run/comparison IDs and returns cases, metrics,
  failures, turns, and tools.

#### BenchmarkReportingService

- **What/why:** Applies ScoringPolicy and compatibility checks to produce
  deterministic totals, rates, rankings, and winners.
- **Receives/returns:** Receives repository snapshots and returns immutable
  reporting contracts.

#### Run Summary · Language Performance · Category Performance · Failure Analysis

- **What/why:** Shows overall results, language/category slices, and failure
  counts/explanations.
- **Receives/returns:** Receives aggregated case evidence and returns summary
  sections.

#### Latency Analysis · Token Analysis · Cost Analysis · Tool Performance · Model Comparison + Winner Explanation

- **What/why:** Shows speed, usage, cost, tool reliability, per-metric winners,
  and the documented overall winner.
- **Receives/returns:** Receives compatible reporting snapshots and returns
  comparison evidence.

**Connection to Stage 11:**
BenchmarkPresentationService exposes reporting contracts without changing
their calculations.

### Stage 11 — Presentation and Export (Stage 16.4)

**Purpose:**
This stage makes read-only benchmark evidence usable by managers and engineers.
It formats reporting data without changing scoring or stored facts.

**Input:** Immutable Stage 16.3 reporting contracts.
**Output:** Dashboard, HTTP responses, Excel/CSV, and manager report.

#### BenchmarkPresentationService

- **What/why:** The read-only facade for report discovery, run detail,
  comparison, and case evidence.
- **Receives/returns:** Receives IDs/filters and returns presentation models.

#### FastAPI Reporting Routes

- **What/why:** Endpoints for runs, details, comparisons, and downloads. They
  are separate from the live invocation API in Stage 2.
- **Receives/returns:** Receive validated parameters and return JSON/files.

#### Next.js Benchmark Dashboard

- **What/why:** Interactive KPIs, charts, filters, case evidence, detailed case
  viewer, and comparison.
- **Receives/returns:** Receives reporting API responses and returns browser
  views.

#### Presentation Exports

- **What/why:** ExcelExporter creates workbooks with native charts and wrapped
  evidence; CsvZipExporter creates deterministic CSV tables.
- **Receives/returns:** Receive reporting contracts and return Excel or CSV ZIP.

#### Manager-Ready Benchmark Report

- **What/why:** Combines metrics, limitations, evidence, comparisons, and winner
  explanations into a decision-ready package.
- **Receives/returns:** Receives reporting data/exports and returns the final
  reviewable report.

**Connection after Stage 11:**
This ends benchmark reporting. Every aggregate remains traceable to persisted
case, turn, tool, metric, and failure evidence.

## Architecture Stage Summary

| Stage | Responsibility | Main Input | Main Output |
|---|---|---|---|
| 1 | Validate and schedule benchmark cases | Fixed 100-case dataset | Isolated benchmark case |
| 2 | Build trusted context and orchestrate execution | Message and trusted identity | Model turn request |
| 3 | Invoke the selected provider | Neutral turn request | Text or tool calls |
| 4 | Bind, validate, authorize, and execute tools | Provider selection | Structured tool outcome |
| 5 | Isolate persistence operations | Domain query/command | Domain record/update |
| 6 | Store business and execution truth | Repository operation | Trusted rows/transaction |
| 7 | Ground continuation and terminate safely | Tool outcome or text | Response, termination, trace |
| 8 | Validate and atomically ingest artifacts | Completed benchmark execution | Persisted analytics |
| 9 | Organize deterministic evaluation | Metrics, tools, turns, failures | Comparable evidence |
| 10 | Aggregate reports and comparisons | Analytics snapshot | Reporting contracts |
| 11 | Present and export results | Reporting contracts | Dashboard and exports |

## Example: How a Customer Request Moves Through the Harness

Consider: **“Where is my order?”**

1. The client sends ModelInvocationRequest to POST /api/v1/model/invoke.
   FastAPI validates the public request.
2. The authentication dependency supplies TrustedCustomerIdentity. The model
   cannot choose or override customer_id, conversation_id, or role.
3. ModelPipelineService protects message/history; ProductionSystemPromptBuilder
   and ContextBuilder produce immutable ConversationContext.
4. build_model_tool_loop composes registries, TrustedSelectionPipeline,
   security services, repositories, OllamaQwenProvider, and the orchestrator.
   This is dependency construction, not model reasoning.
5. BoundedModelToolLoopService creates provider turn 1 and sends
   ModelToolLoopTurnRequest with context and approved tool definitions.
6. Qwen requests list_current_orders or get_order_status instead of guessing.
   Tool-call detection preserves the call ID and arguments.
7. ToolRegistry confirms the tool. TrustedArgumentBinder takes identity only
   from ExecutionContext. OrderEntityResolver verifies any order in the
   authenticated customer's repository scope; ConversationState cannot
   authorize or directly inject it.
8. ToolSelectionResolver validates bound arguments. Role, tool, ownership, and
   privacy checks approve or stop execution.
9. SingleToolExecutionGateway invokes the tool exactly once. The tool reads
   PostgreSQL through OrderRepository and never treats model identity as
   authority.
10. Repository data becomes ToolResult and ToolExecutionOutcome.
    BusinessGroundingPolicy recognizes verified transactional evidence.
11. ToolContinuationCycle formats the result for Ollama. Qwen now explains
    verified status instead of inventing it.
12. The response is validated and privacy-protected. Termination & Safety
    Policies record the outcome and clean temporary state.
13. OrchestrationExecutionTrace records provider turns, tool executions,
    timing, termination, correlation, and cleanup without raw secrets.
14. For a benchmark case only, the evidence becomes
    CompletedConversationExecution and child artifacts.
    BenchmarkIngestionService validates, sanitizes, cost-maps, and atomically
    persists them. Live traffic does not require benchmark ingestion to return
    its response.

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
Browser → Vercel Next.js dashboard → Render FastAPI service → Render PostgreSQL
```

The dashboard is read-only with respect to benchmark reporting. It uses the
existing Stage 16 reporting endpoints and never fabricates benchmark data.
The Render backend uses the existing SQLAlchemy session layer and Alembic
migrations.

### Required environment variables

Configure secrets in Render or Vercel, never in Git.

| Platform | Variable | Purpose |
|---|---|---|
| Render | `DATABASE_URL` | Existing Render PostgreSQL connection string |
| Render | `ENVIRONMENT=production` | Disables development debug behavior |
| Render | `CORS_ALLOWED_ORIGINS` | Comma-separated exact frontend origins, such as `https://your-dashboard.vercel.app` |
| Render | `AUTHENTICATION_HMAC_SECRET` | Existing authentication signing secret, at least 32 random characters |
| Render | `SECURITY_AUDIT_PSEUDONYM_KEY` | Separate security-audit pseudonym key |
| Vercel | `NEXT_PUBLIC_API_BASE_URL` | HTTPS Render URL ending in `/api/v1` |
| Vercel | `NEXT_PUBLIC_API_TIMEOUT_MS` | Browser API timeout; default `30000` |

Ollama settings are not required for read-only benchmark reporting. Do not
expose a local Ollama endpoint publicly merely to serve the dashboard.

### Deploy the FastAPI backend to Render

The root `render.yaml` defines the service with `backend/` as its root directory.
Its commands are:

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

### Deploy the Next.js dashboard to Vercel

Import the same GitHub repository in Vercel and set the project root directory
to `frontend`. Configure `NEXT_PUBLIC_API_BASE_URL` with the Render HTTPS URL,
for example `https://cx-harness-benchmark-api.onrender.com/api/v1`, then deploy
with:

```bash
npm ci
npm run build
```

After Vercel assigns the final domain, add that exact HTTPS origin to the Render
`CORS_ALLOWED_ORIGINS` value and redeploy the backend. Keep
`http://localhost:3000` only when local development access is required.

### Verify the deployment

1. Open `https://<render-service>/health` and confirm the response is
   `{"status":"ok","service":"cx-harness-api"}`.
2. Open `https://<render-service>/api/v1/benchmark-reporting/runs` and confirm
   stored benchmark runs are returned, or an explicit empty list if the
   database has no runs.
3. Open `https://<vercel-project>/benchmark-reporting` and verify run listing,
   run detail, comparison, and Excel/CSV downloads.
4. Confirm browser requests use HTTPS and the Render API returns the exact
   Vercel origin in `Access-Control-Allow-Origin`.

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
