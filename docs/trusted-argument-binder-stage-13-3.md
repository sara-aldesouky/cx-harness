# Stage 13.3 — Trusted Argument Binder

Stage 13.3 adds an isolated provider-neutral boundary between a model-suggested
tool selection and the existing `ToolSelectionResolver`. It is not connected to
the production runtime and never validates tool schemas or executes tools.

## Mandatory order trust boundary

The binder never reads an order number from `ConversationState` and has no
repository dependency. It constructs an `EntityResolutionRequest` and accepts
an order only from `EntityResolutionResult(status=resolved)`:

```text
ConversationState → OrderEntityResolver → customer-scoped repository
→ ResolvedEntity.public_reference → TrustedArgumentBinder → order_number
```

State references from verified tool results or repository lookup are still
reverified by Stage 13.2. Explicit-customer-input and future model-derived state
sources cannot bind directly. Every non-success resolver status produces no
`BoundToolSelectionRequest`; provider and state fallback are prohibited.

## Protected context values

`customer_id` and `conversation_id` exist in `TrustedExecutionValues`. The
binder discards provider overrides and records `EXECUTION_CONTEXT` provenance.
The current write input schemas intentionally do not declare these fields, so
they remain trusted sideband context and are not inserted into the schema
argument mapping. This preserves existing schemas and the execution-context
security boundary.

`order_number` is inserted into the argument mapping only with
`VERIFIED_ENTITY_RESOLUTION` provenance. A provider value is replaced even when
it happens to equal the verified value. Diagnostics retain only the safe
`replaced_model_value` boolean, never the discarded value.

## Policies and unknown arguments

Immutable `ToolBindingPolicy` declarations cover exactly `cancel_order`,
`update_delivery_address`, `initiate_refund`, and `create_support_ticket` using
their existing argument names. The registry is explicit, per-instance,
thread-safe, duplicate-protected, and deterministically listed.

Unknown tools and tools without policies fail closed. Unexpected arguments are
rejected by the production write policies. A policy may explicitly choose to
discard unexpected values. Unprotected declared arguments retain
`MODEL_SUGGESTED` provenance; completeness and confirmation are deferred to
Stage 13.4.

## Resolution mapping

| Resolver result | Binding result |
|---|---|
| `RESOLVED` | `BOUND` |
| `CLARIFICATION_REQUIRED` with multiple candidates | `AMBIGUOUS_ENTITY` |
| `CLARIFICATION_REQUIRED` | `CLARIFICATION_REQUIRED` |
| `NOT_FOUND`, `EXPIRED`, `STALE` | `RESOLUTION_FAILED` |
| `FORBIDDEN`, `INVALID_REFERENCE` | `UNTRUSTED_ARGUMENT` |

The resolver's customer-safe message and status remain attached to the failure.
No raw messages, identifiers, model values, state snapshots, addresses, reasons,
or issue descriptions are logged by this subsystem.

## Startup schema compatibility

`PolicySchemaCompatibilityValidator` compares immutable, provider-neutral
`RegisteredToolSchema` descriptors with binding policies. Descriptors are
supplied by a future composition root; the binding package does not import the
tool registry or business schemas. Validation fails before serving traffic when:

- A policy and schema name differ.
- A policy inserts an argument absent from the schema.
- Protected classification differs.
- A required schema field is missing or optional in policy.
- A non-schema policy argument is not an approved execution-context sideband.

`RegistryCompletenessValidator` optionally checks that every executable write
schema has exactly one policy and that no orphan policy exists. Duplicate schema
descriptors fail. Duplicate policies remain prevented atomically by the policy
registry. Neither validator performs per-request schema validation.

At a future production composition boundary, neutral descriptors must be
derived from the real registered Pydantic tool schemas and immediately passed
to these validators. They must not become a second handwritten production
schema catalogue. A mismatch must fail application startup. Stage 13.3 does not
perform that composition or import the production tool registry.

## Resolver failure contract

The binder handles resolver boundaries explicitly and fail-closed:

| Failure | Safe code |
|---|---|
| Timeout | `resolver_timeout` |
| Active `asyncio.CancelledError` | re-raised unchanged |
| Dependency `concurrent.futures.CancelledError` | `resolver_cancelled` |
| Unexpected exception | `resolver_unavailable` |
| Non-contract return | `invalid_resolver_response` |
| Malformed resolution contract | `invalid_resolver_contract` |

Dependency failures use the same customer-safe availability message. Raw
exception text and malformed response content are discarded. Active asyncio
cancellation is a lifecycle control signal (client disconnect, shutdown, or
structured-concurrency cancellation), so no binding result or audit metadata is
created. `KeyboardInterrupt` and `SystemExit` likewise propagate unchanged.

## Trusted execution extensibility

`TrustedExecutionValues` retains required customer and conversation identities.
Its backward-compatible `extensions` field is strictly bounded metadata, not a
trusted-claim or argument channel. The binder and policies never inspect it.

Extension keys use `^[a-z][a-z0-9_]{0,63}$`, cannot contain surrounding
whitespace, and are unique after case-insensitive normalization. An explicit
frozen set blocks identity, authorization, approval, order, idempotency, role,
scope, and bypass names. Security prefixes (`auth_`, `authorization_`,
`identity_`, `permission_`, `role_`, `scope_`, `trusted_`, `protected_`,
`system_`, and `internal_`) are also reserved.

Values are limited to null, booleans, bounded integers, bounded finite floats,
strings, immutable sequences, and mappings recursively containing the same
domain. UUIDs, datetimes, decimals, bytes, sets, callables, classes, exceptions,
Pydantic models, NaN/infinity, and application objects are rejected. Limits are:

- 32 top-level entries.
- 64 characters per key and 4,096 characters per string.
- 64 entries per nested mapping or sequence.
- Six nested levels.
- 16,384 normalized UTF-8 JSON bytes total.
- Integers within the interoperable JSON range ±9,007,199,254,740,991 and
  finite floats with absolute value no greater than `1e308`.

Mappings are key-sorted, deeply frozen, defensively copied, and deterministically
serialized. Extensions cannot supply protected arguments, override core
identity, grant authorization, change resolution, or appear in tool-schema
arguments, failures, or sanitized audit metadata.

## Immutable JSON ownership and parity

Stage 13.3 intentionally owns a small private immutable-JSON helper to avoid an
import dependency on `app.tools`. For the overlapping domain—strings, booleans,
integers, finite floats, nulls, lists/tuples, and nested mappings—its freeze and
copy behavior matches the existing shared helper, including mutation isolation
and preservation of mapping iteration order. Both generic helpers pass through
unsupported objects; contracts using them remain responsible for validation.
The stricter extension-metadata validator is intentionally different: it rejects
unsupported values, sorts mappings, and enforces resource/security limits.

## Sanitized audit metadata

Every binder result carries `BindingAuditMetadata`, containing only:

- Binding status.
- Protected, injected, and replaced counts.
- Sorted unique provenance categories.
- Resolver outcome.

It contains no identifiers, UUIDs, arguments, messages, state, addresses,
reasons, or secrets. Stage 13.3 defines this value but introduces no logger or
audit sink.

## Concurrency and isolation

The binder has no per-request mutable state. Known tool names are frozen at
construction, requests and results are immutable, and policies are defensively
copied under the registry lock. One binder can safely serve concurrent calls
provided its injected resolver honors its own concurrency contract.

The package uses private immutable-JSON helpers. A clean-interpreter import test
also verifies that loading `app.argument_binding` does not transitively load the
Stage 13.2 repository adapter. Stage 13.2 retains the same public exports through
lazy package attributes. Stage 13.3 does not import FastAPI,
runtime services, providers, prompts, tool packages, authorization, repositories,
SQLAlchemy, database models, the tool loop, or business/write operations.
