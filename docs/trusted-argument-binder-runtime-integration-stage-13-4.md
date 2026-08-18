# Stage 13.4 — Trusted Argument Binder Runtime Integration

Stage 13.4 connects the frozen Stage 13.3 binder to the production bounded
model/tool loop. It does not change Stage 13.3 contracts, policies, validation,
cancellation, metadata, or dependency boundaries.

## Production flow

```text
Provider response
  → provider-neutral ToolSelectionRequest
  → TrustedSelectionPipeline
  → TrustedArgumentBinder (exactly once)
  → BoundToolSelectionRequest
  → existing ToolSelectionResolver schema validation
  → ValidatedToolSelection
  → ToolExecutionRequestFactory
  → role policy
  → tool authorization
  → ownership authorization
  → business tool
  → ToolResult and provider continuation
```

`BoundedModelToolLoopService` requires `TrustedSelectionPipeline`; it no longer
accepts a raw `ToolSelectionResolver`. Consequently, the production loop has no
selection-to-execution route that can skip binding.

## Integration boundary

For each provider selection, `TrustedSelectionPipeline`:

1. Requires trusted customer and conversation identities from
   `ExecutionContext`.
2. Loads the optional immutable conversation-state snapshot.
3. Copies the provider-neutral selection into the frozen Stage 13.3 input
   contract without changing its name, call ID, or proposed arguments.
4. Invokes the binder exactly once.
5. Stops on every non-success binder result.
6. Constructs the schema-validation request exclusively from the successful
   `BoundToolSelectionRequest`.
7. Preserves only the original tool version because version resolution is not a
   binder responsibility.

The raw provider argument mapping is not referenced after binding succeeds.

### Conversation-state dependency semantics

State dependency is declarative at the Stage 13.4 integration boundary. Tools
not listed as state-dependent remain stateless: a missing or unavailable
optional snapshot cannot prevent an otherwise trusted explicit or
repository-resolved request. A tool declared in `state_required_tools` fails
closed before binding when its snapshot is missing, unavailable, malformed,
owned by another conversation, expired, or inactive. Production currently has
no tool whose contract requires state; protected order operations can resolve
explicit customer references or deterministic customer-scoped repository
fallbacks without it.

Conversation state never supplies customer or conversation identity. Those
values always come from the authenticated `ExecutionContext`, and any loaded
snapshot is partition-checked against that trusted conversation ID.

## Policies and startup validation

The runtime policy registry contains the four frozen protected write policies.
For registered unprotected tools, composition derives pass-through binding
requirements from their actual Pydantic input schemas. This ensures every
executable provider selection still crosses the binder without expanding the
frozen Stage 13.3 policy catalogue.

Before serving traffic, runtime composition derives neutral schema descriptors
from the registered tool classes and runs the frozen compatibility and
completeness validators. A mismatch fails startup. Descriptors are never a
separate handwritten production schema source.

## Order resolution and sessions

Protected `order_number` arguments are accepted only from the frozen
`OrderEntityResolver`. `SessionFactoryOrderResolutionRepository` opens a
short-lived SQLAlchemy session for each customer-scoped resolver query and
delegates to the established repository adapter. It performs no writes.

Provider order identifiers are discarded. The resolver verifies an explicit
customer reference, a trusted state reference, or an allowed deterministic
fallback against the authenticated customer before the binder produces the
protected argument.

## Failure flow

A binder rejection is carried as a structured `ArgumentBindingResult` inside
`TrustedArgumentBindingRejected`. The bounded loop maps its safe error code and
public message into the existing structured loop failure.

On binding failure:

- Schema validation is not called.
- Authorization is not called.
- The execution gateway is not called.
- No `ToolCall` audit lifecycle starts.
- No business operation or repository write occurs.
- Binding is not retried and provider arguments are never used as fallback.

Unexpected integration errors continue through the existing safe invalid-call
termination path. Active Stage 13.3 cancellation behavior remains unchanged.

## Authorization and ToolCall auditing

The execution request is created only from `ValidatedToolSelection`, which in
turn is created only from the successful bound request. Role, exact-tool, and
ownership authorization therefore see the normalized bound arguments and the
trusted execution context. They do not receive the provider selection or the
conversation-state object.

`ToolExecutor` starts the ToolCall audit lifecycle only after all authorization
checks pass. Its sanitized input payload comes from the rehydrated validated
input model, so discarded provider identifiers and raw provider arguments
cannot reach persistence.

## Security invariants

- Trusted customer and conversation IDs come only from `ExecutionContext`.
- Conversation state is context, not authorization.
- Protected orders are customer-scoped and repository-verified.
- Schema validation consumes bound arguments only.
- Authorization consumes the resulting validated execution request.
- Business operations receive only bound, validated, authorized arguments.
- Providers and business tools remain unaware of binding internals.
- The binder remains schema-neutral and execution-neutral.
