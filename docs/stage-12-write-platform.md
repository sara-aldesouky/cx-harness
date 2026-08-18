# Stage 12 Write Platform — Final Architecture and Acceptance

## Status

Stage 12 provides a consistent, provider-independent write boundary for four
customer operations. All shared execution behavior is owned by the framework;
each concrete operation contains only validated domain policy, locked state
rechecking, and its minimal mutation.

## Overall architecture

```text
Stage 11 trusted security decision
  -> immutable WriteExecutionContext
  -> WriteFrameworkExecutor
       -> declaration and input contract checks
       -> operation.validate() outside the transaction
       -> TransactionManager.execute()
            -> acquire aggregate lock
            -> re-evaluate mutable policy
            -> operation.apply()
            -> validate declared output type
            -> commit or automatic rollback
       -> standardized WriteResult
       -> best-effort safe WriteAuditEvent
       -> caller
```

The framework does not import a model provider or Stage 9 orchestration. Its
transaction port is database-neutral; SQLAlchemy is isolated in one transaction
adapter and in operation persistence adapters.

## Layer responsibilities

### Immutable contracts

- `WriteExecutionContext` carries trusted customer identity, request and
  correlation IDs, request time, and proof that Stage 11 gates passed.
- `WriteSecurityEnvelope` fails closed unless authentication, role policy, tool
  authorization, and ownership authorization all succeeded.
- `WriteValidationDecision` represents pre-transaction domain eligibility.
- `WriteResult` and `WriteError` define one safe success/failure shape.
- `WriteAuditEvent` contains minimal non-sensitive execution facts.

### Framework executor

The executor owns lifecycle ordering, contract checks, safe error translation,
output validation, audit invocation, and audit-failure isolation. It invokes a
transaction callback exactly once and performs no automatic retry.

### Transaction manager

`TransactionManager` is the generic transaction port.
`SQLAlchemyTransactionManager` opens and closes the session transaction,
commits only after callback completion, rolls back every exception path, and
converts infrastructure details into a safe framework error.

### Business operations

Each operation owns its immutable input/output contracts, declarative policy,
customer-safe messages, safe audit reference, and aggregate-specific storage
ports. Operations never begin, commit, roll back, flush, retry, invoke providers,
or write audit records directly.

## Supported capabilities

| Capability | Aggregate and mutation | Idempotent behavior |
|---|---|---|
| Cancel order | Lock owned order; set eligible status to `cancelled` and update timestamp | Terminal cancelled state is not rewritten |
| Update delivery address | Lock owned order; replace address while eligible | Normalized equal address performs no update |
| Initiate refund | Lock owned order; create pending refund plus requested event atomically | Existing refund prevents a second refund/event |
| Create support ticket | Lock customer then optional order; create active issue ticket | Existing issue fingerprint returns the active ticket |

No operation performs settlement, shipment workflow, ticket workflow, provider
calls, or any business behavior outside the documented mutation.

## Consistent execution and errors

All operations use the same flow and produce the same contract categories:

- domain rejection: `failure`, validation phase, stable public code/message;
- transaction failure: `failure`, transaction phase, no internal detail;
- preflight or unexpected infrastructure failure: `failure`, infrastructure
  phase, generic safe message;
- completion: `success`, declared immutable outcome, no error.

Missing resources and ownership mismatches deliberately use indistinguishable
customer-safe failures. Invalid operation declarations remain programmer errors
and fail before transaction entry.

## Transaction and rollback guarantees

- Ordinary validation completes before the transaction begins.
- Mutable rules are re-evaluated after acquiring the aggregate lock.
- Output type validation occurs inside the transaction before commit.
- Refund and refund-event creation commit or roll back together.
- Mutation, constraint, output, timeout, and unexpected transaction exceptions
  roll back the entire unit of work.
- No concrete operation calls transaction-control methods.

## Concurrency guarantees

- Cancellation, address update, and refund initiation lock the order row.
- Ticket creation locks customer first and optional order second.
- Stable lock ordering avoids customer/order lock cycles.
- Parent locking serializes duplicate checks before mutation.
- The ticket active-issue partial unique index and reference unique index provide
  final database enforcement.
- Real PostgreSQL tests use bounded futures and synchronized preflight barriers
  to verify completion without deadlock or orphaned state.

## Idempotency guarantees

Business-state idempotency remains correct even when retries use different
request IDs. Normalized request values, terminal state checks, locked duplicate
rechecks, fingerprints, and database constraints ensure one logical change.
Trusted `request_id` is ready to receive a future transport idempotency key if
exact response replay becomes an API requirement.

## Audit guarantees

- Audit occurs only after validation rejection or transaction completion.
- Audit failure cannot reverse a commit or change the returned result.
- Events omit raw customer identity, descriptions, addresses, payment IDs, and
  database errors.
- `business_change_applied` distinguishes mutations from successful idempotent
  no-ops, preventing retry traffic from appearing as repeated business actions.
- Request and correlation IDs support downstream trace and sink deduplication.

## Security guarantees

- Customer identity comes only from trusted `ExecutionContext`, never tool input.
- The framework fails closed when any security-envelope gate is false.
- Ownership is evaluated in preflight and again using locked transactional state.
- Customer-visible outputs omit internal UUIDs and sensitive payment data.
- Errors and audit records do not expose SQL, stack traces, credentials, PII, or
  authorization internals.

## Performance and operational assumptions

- Transactions contain only locked consistency reads, mutation, and output
  construction; external calls and audit sinks stay outside lock scope.
- Each operation locks the smallest stable aggregate root needed for correctness.
- Support-ticket transactional state reuses its locked customer/order rows and
  does not re-query them.
- PostgreSQL must support `SELECT ... FOR UPDATE` and the ticket partial index.
- Callers must use the framework rather than invoking `apply()` directly.
- Audit delivery is best effort at this boundary; durable security audit
  infrastructure remains the responsibility of the existing Stage 11 subsystem.
- Database availability, backups, connection-pool sizing, statement timeouts,
  and deployment migrations remain operator responsibilities.

## Extension checklist

A future write capability must:

1. Define strict frozen input and customer-safe output contracts.
2. Implement `BaseWriteOperation` with a stable name and semantic version.
3. Keep domain policy centralized and validate before transaction entry.
4. Identify and lock one stable aggregate root in documented global order.
5. Recheck mutable authorization, eligibility, and duplicates under the lock.
6. Perform all related mutations through the supplied transaction.
7. Return the declared output type before commit.
8. Define safe deterministic success, failure, and audit semantics.
9. Override `business_change_applied()` when success can mean an idempotent no-op.
10. Add unit, rollback-injection, concurrent, and real PostgreSQL tests.

## Known future work

The following are intentionally not implemented by Stage 12:

- HTTP write endpoints and transport-level idempotency-key/result replay;
- distributed idempotency record storage;
- additional write capabilities;
- write-specific dashboards or workflow engines;
- background settlement, delivery, or support processing;
- automatic transaction retries.

These additions can use the current contracts without moving security,
transaction, idempotency, or audit concerns into business operations.

## Acceptance conclusion

The platform has one lifecycle, one transaction owner, one result model, one
safe failure strategy, and one audit boundary. Its current operations have unit,
rollback, idempotency, concurrency, and PostgreSQL integration coverage. With
its documented operational assumptions, Stage 12 is ready to support future
write capabilities without redesigning Stage 9, providers, or Stage 11.
