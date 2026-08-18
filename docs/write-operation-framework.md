# Write Operation Framework

## Purpose and boundary

The write-operation framework is the shared application boundary for business
changes. It defines how a validated and authorized request enters
a transaction, produce a safe result, and emit an audit observation. It does
not implement a business write, expose an API, or alter any database schema.

The framework is provider-, domain-, and database-independent. A future write
capability supplies its business validation and mutation callback; the
framework owns the surrounding lifecycle.

## Lifecycle

```text
Authenticated identity
  -> role policy approved
  -> tool authorization approved
  -> ownership authorization approved
  -> immutable WriteExecutionContext
  -> operation input contract check
  -> business validation
  -> framework-owned transaction
  -> operation apply callback
  -> output contract check
  -> commit or rollback
  -> standardized WriteResult
  -> best-effort safe audit observation
```

`WriteSecurityEnvelope` is trusted evidence that the existing Stage 11 gates
have already approved the request. The executor fails closed when any gate is
missing. It does not replace or reimplement those security services.

## Trusted write context

`WriteExecutionContext` contains the existing trusted `ExecutionContext`, a
request ID, correlation ID, timezone-aware request timestamp, and the security
envelope. A trusted customer identity is mandatory. None of these values may be
accepted from model-generated tool arguments.

## Validation responsibility

The framework validates operation declarations, context, and input model types.
Each business operation owns its domain rules in `validate()` and returns
an immutable `WriteValidationDecision`. A denied decision produces a structured
validation failure before a transaction is opened. Business rules therefore
remain close to their future capability without duplicating transaction or
transport behavior.

## Transaction ownership

`TransactionManager` is the database-neutral transaction boundary.
`SQLAlchemyTransactionManager` adapts it to the existing session factory:

- a successful callback and valid output commit automatically;
- any exception, including an invalid output contract, rolls back automatically;
- sessions are scoped and closed by SQLAlchemy's context manager;
- business operations never call `commit()` or `rollback()`.

The executor calls an operation exactly once. Expected validation failures do
not open a transaction. Transaction and infrastructure failures are returned as
safe standardized failures with no database or exception details.

## Result contract

Every operation returns an immutable `WriteResult` with exactly one valid shape:

- `success`: an outcome, no error, a safe message, and optional immutable metadata;
- `failure`: a structured `WriteError`, no outcome, and a safe message.

Failure phases distinguish validation, transaction, and infrastructure failures.
Serialization is deterministic and JSON-compatible.

## Audit compatibility

The optional observer receives a minimal `WriteAuditEvent` containing operation
identity, request/correlation IDs, status, and safe failure codes. It contains no
business payload or raw customer identity. Observer failures cannot change an
already completed or safely rejected result, preserving the existing Stage 11
audit-resilience principle.

## Adding a future write capability

To add a future write operation:

1. Define strict Pydantic input and customer-safe output models.
2. Implement `BaseWriteOperation` with stable name and version declarations.
3. Put domain preconditions in `validate()`.
4. Put only the atomic business mutation in `apply()` using the supplied transaction.
5. Register and authorize the operation through the existing security architecture.
6. Invoke it through `WriteFrameworkExecutor`; never manage transactions in the operation.

Stage 12.1 intentionally supplied no registration, routing, or concrete
business write. Stages 12.2–12.5 added the current operations without changing
the framework boundary.
