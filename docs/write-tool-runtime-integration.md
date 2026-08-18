# Stage 12.9 — Write Tool Runtime Integration

## Why the bridge was required

Stage 10 capabilities already implemented `BaseTool` and were discoverable by
the bounded model loop. Stage 12 writes intentionally implemented the separate
`BaseWriteOperation` contract so business mutations could share validation,
transaction, rollback, idempotency, and audit guarantees. Before Stage 12.9,
the runtime had no safe boundary connecting those contracts.

Stage 12.9 adds that boundary without moving write policy into model tools and
without changing the Stage 9 loop or a provider.

## Runtime architecture

Before:

```text
Model loop -> ToolRegistry -> Stage 10 read BaseTool

Stage 12 BaseWriteOperation -> WriteFrameworkExecutor (not model discoverable)
```

After:

```text
Customer conversation
  -> unchanged bounded model loop
  -> ToolRegistry
  -> Stage 11 role / exact-tool / ownership gateway
  -> execution-local trusted security approval
  -> write BaseTool adapter
  -> WriteExecutionContext
  -> WriteFrameworkExecutor
  -> SQLAlchemyTransactionManager
  -> existing BaseWriteOperation
  -> commit or rollback
  -> WriteResult -> safe ToolResult
  -> existing continuation adapter
  -> next provider turn and final response
```

## Exposed write tools

The production registry now includes exactly:

- `cancel_order`;
- `update_delivery_address`;
- `initiate_refund`;
- `create_support_ticket`.

All existing Stage 10 registrations remain present and retain their names,
versions, schemas, and behavior. Registry ordering remains deterministic.

## Adapter responsibilities

Each adapter:

1. declares provider-neutral tool metadata;
2. reuses the corresponding frozen Stage 12 input schema;
3. consumes trusted runtime identity and gateway approval;
4. constructs an immutable `WriteExecutionContext`;
5. constructs the existing operation with injected persistence adapters;
6. calls `WriteFrameworkExecutor` exactly once;
7. maps `WriteResult` to a customer-safe `ToolResult`;
8. contains no business eligibility, mutation, transaction, or retry policy.

Model arguments cannot contain trusted customer, conversation, trace, request,
correlation, payment, settlement, status, priority, assignment, or internal-note
fields. Pydantic rejects unknown fields before execution.

## Trusted-context construction

`SingleToolExecutionGateway` already evaluates role policy, exact-tool policy,
and ownership before calling `ToolExecutor`. It now scopes an immutable
`ToolExecutionSecurityApproval` to that single synchronous invocation using a
`ContextVar`. The context is automatically cleared on success or exception and
is isolated between concurrent executions.

The adapter fails closed unless all four facts are true:

- authenticated customer identity exists;
- role policy allowed the capability;
- exact-tool authorization allowed the tool/version;
- ownership authorization allowed the resource.

The approval is application-created state, not a tool argument. The adapter
maps it to the existing `WriteSecurityEnvelope`. `request_id` comes from trusted
`ExecutionContext.execution_id`, `correlation_id` comes from `trace_id`, and
the original conversation/model context remains unchanged.

## Dependency composition and lifetime

`WriteToolFactory` is created once with the production session factory and one
write-audit observer. `ToolExecutor` retains the existing per-call tool-instance
lifecycle and asks this factory to construct registered tools. Read tools still
use their normal zero-argument construction. Write tools receive the shared
runtime dependencies without globals or provider knowledge.

Each write invocation constructs lightweight, stateless operation, reader,
transaction-manager, and executor objects. SQLAlchemy sessions still open only
inside established reader and transaction scopes. No session is shared across
requests or model turns.

## Result translation

A successful write returns `WriteToolOutput` containing only:

- operation name and safe status;
- stable completion/no-change result code;
- customer-safe message;
- safe order or ticket reference when available;
- whether a business change was applied;
- whether the result was an idempotent no-op;
- safe retry guidance.

Expected rejection becomes a standard `ToolError` using the existing public
code and message. Unexpected adapter construction failures use the generic
`write_adapter_unavailable` failure. SQL, exception strings, UUIDs, payment IDs,
security objects, policy details, and audit internals are never returned.

## Security and ownership

Write metadata is not read-only, but it still requires trusted customer identity
and optional order ownership. The existing ownership service now accepts
approved write metadata while retaining the same order lookup and indistinguishable
not-found/foreign-resource response. Cross-customer attempts stop in the
gateway before `ToolExecutor`, `WriteFrameworkExecutor`, or business mutation.

Support escalation declares the provider-neutral `support` capability. Central
role and exact-tool registries derive permissions from metadata; no provider or
operation contains hard-coded role checks.

## Audit behavior

The two established audit boundaries retain distinct responsibilities:

- `ToolExecutor` creates and finalizes one `ToolCall` record for an invoked tool;
- the Stage 12 observer records one mutation outcome from the write framework.

The adapter creates neither record directly. `LoggingWriteAuditObserver`
pseudonymizes request and correlation IDs and emits only the existing safe
Stage 12 event fields. `business_change_applied` distinguishes actual mutations
from concurrent idempotent no-ops. Observer failure cannot change a committed
result. A gateway security denial occurs before either execution audit begins.

## Idempotency and failure behavior

All duplicate and rollback behavior remains in Stage 12:

- cancelled state prevents a second cancellation;
- normalized equal addresses are not rewritten;
- order locking prevents duplicate refunds and refund events;
- fingerprint, locks, and partial uniqueness prevent duplicate active tickets.

Invalid provider arguments are rejected during selection. Missing approval or
identity fails closed. Business, transaction, repository, and infrastructure
failures are mapped through the existing framework and then to safe tool
failures. Successful writes continue through the existing provider continuation
path.

Stage 9 intentionally terminates immediately on a tool business failure with
`TOOL_BUSINESS_FAILURE` and a safe final message. Stage 12.9 preserves that
accepted behavior rather than forcing an additional provider turn.

## Verification coverage

The test suite verifies:

- all read and write registrations coexist without duplicate names;
- provider schemas contain no trusted or internal fields;
- missing/incomplete approval and missing identity fail closed;
- all four writes mutate real isolated PostgreSQL state through the gateway;
- repeated calls do not duplicate state or audit mutations;
- all four cross-customer attempts stop before execution;
- malformed/identity-injected arguments fail before execution;
- Arabic cancellation and refund, plus Franco-Arabic address and support flows,
  complete through a scripted provider, unchanged bounded loop, real gateway,
  real write framework, PostgreSQL, tool result, and final provider response;
- safe business rejection follows the existing Stage 9 termination policy.

## Exposing a future write operation

1. Complete and accept a `BaseWriteOperation` with transaction/idempotency tests.
2. Add one strict model-controlled input schema if the operation input is not
   already safe for exposure.
3. Add one thin adapter using `WriteToolOutput` and trusted approval.
4. Declare capability, identity, ownership, and policy metadata.
5. Add the adapter to the explicit write registration tuple.
6. Extend the injected factory construction without adding business policy.
7. Prove security denial, PostgreSQL mutation, repeat safety, audit behavior,
   and provider continuation through the bounded runtime.

## Deferred to Stage 13

Stage 12.9 does not add model-quality evaluation, benchmark scoring, prompt
engineering, additional writes, HTTP write endpoints, streaming, retries, or
provider-specific code. Stage 13 can now validate realistic conversations
because the production runtime can discover and safely execute both read and
approved write capabilities.
