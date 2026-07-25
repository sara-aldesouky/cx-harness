# Stage 11 Final Security Acceptance Review

## 1. Executive Summary

**Decision: PASS WITH REQUIRED FOLLOW-UP**

Stage 11 provides coherent defense in depth across authentication, role policy,
exact-tool authorization, ownership authorization, privacy protection, and
security audit. The focused security suite and complete backend regression are
green. Trusted identity cannot be supplied by model arguments, denied requests
stop before business tool execution and ToolCall creation, protected-resource
responses resist enumeration, and security audit records are pseudonymous.

The architecture is suitable for a single-process deployment. A distributed or
multi-worker production deployment requires a shared atomic replay store before
launch. Central audit delivery, key rotation, secret management, and monitoring
are also production operational requirements.

One genuine dependency defect was corrected during review: importing security
modules before `app.tools` exposed a circular dependency through the eager tool
exports. Security policy types are now type-only dependencies in the runtime
composition modules, with runtime exception imports deferred locally. Execution
behavior is unchanged and both import orders are verified.

## 2. Architecture Assessment

The control flow remains:

```text
Credential verification and replay check
  -> trusted identity
  -> role capability policy
  -> exact tool/version authorization
  -> ownership authorization
  -> privacy projection
  -> read-only business tool
  -> privacy-safe audit and response
```

Responsibilities are separated cleanly. Providers do not authenticate or
authorize. Business tools do not interpret roles. Ownership resolution remains
repository-backed and read-only. Audit is best-effort and cannot convert a
denial into an allow or break an otherwise safe customer response.

Dependency direction is materially sound after removing the import cycle. The
remaining security modules depend on immutable tool metadata and execution
contracts, not provider implementations.

## 3. Security Assessment

- Authentication fails closed for missing, malformed, expired, revoked,
  replayed, incorrectly signed, or replay-store-unavailable credentials.
- Signed roles cannot be replaced by user text or tool arguments.
- Session-token reuse and one-time-token consumption are explicit policies.
- Exact tool name and version policies run before ownership and execution.
- Cross-customer and absent protected resources share one generic public 404.
- Unauthorized requests create no ToolCall execution record.
- Prompt injection cannot replace trusted customer identity or role context.
- Provider prompts, logs, errors, and public responses use centralized privacy
  protection.
- Audit events use pseudonymous identities and stable reason codes without raw
  tokens, JTIs, UUIDs, or customer PII.
- Business capabilities remain read-only.

## 4. Layer-by-Layer Review

### 11.1 Authentication and 11.7.1 replay protection

The HMAC credential carries subject, signed role, issued-at, expiry, UUID JTI,
and usage policy. Signature and lifecycle validation occur before trusted
identity creation. Replay storage is abstracted behind a provider-independent
contract. The in-memory implementation is bounded, thread-safe, cleans expired
state, and fails closed rather than evicting active security markers.

### 11.2 Ownership authorization

Customer identity comes only from trusted execution context. Transactional
resources use the shared order-ownership resolver. Ownership mismatch and
absence remain distinguishable internally but normalize to the same public
response. Public Knowledge correctly bypasses ownership checks.

### 11.3 Roles and access policies

Roles and capability policy are centralized and immutable. Business tools do
not contain role checks. Current permissions are consistent with the current
customer-facing read tools. Before adding future operational capabilities, the
policy model should add explicit intended-audience metadata rather than granting
new capability enum values to every role automatically.

### 11.4 Tool authorization

Authorization is exact by tool name and version. Unknown tools, missing policy,
and disallowed roles fail before tool construction or execution. The policy
registry is composed from the actual runtime registry and does not use provider
or prompt data.

### 11.5 Data protection

Field rules, text masking, prompt sanitization, response projection, error
sanitization, and log filtering are centralized. Trusted identifiers remain
available only inside security and repository boundaries. Future dynamically
added logging handlers must receive equivalent privacy filters.

### 11.6 Audit logging

Events have stable types, severity, category, result, safe reason codes, and
pseudonymous correlation. Primary sink failures fall back safely and never
affect business decisions. Production requires durable centralized delivery and
monitoring of sink failures.

### 11.7 validation

The abuse catalogue covers credential tampering, ownership bypass, role and tool
escalation, prompt injection, disclosure attempts, audit failures, concurrency,
and fail-closed behavior. Stage 11.7.1 adds focused concurrent replay and
uniform-resource-response coverage.

## 5. Remaining Risks

1. The replay store is process-local. Separate workers do not share revocation
   or one-time consumption state.
2. HMAC credentials have no key identifier or overlapping-key rotation model.
3. Logout/token issuance are outside this repository; the revocation contract
   exists, but no account-management endpoint invokes it.
4. The default audit sink is application logging rather than a durable SIEM
   transport.
5. Privacy log filters cover handlers installed at application startup; later
   handlers need explicit integration.
6. Rate limiting, automated credential-stuffing defense, and live adversarial
   model testing remain separate operational controls.

## 6. Production Readiness

- **Single process:** Architecturally ready with production secret management,
  durable audit shipping, and operational monitoring.
- **Multiple workers on one host:** Not ready until replay/revocation state is
  shared atomically.
- **Distributed deployment:** Requires Redis or database replay storage with
  atomic consume/revoke operations and TTL cleanup, centralized audit/SIEM,
  managed key rotation, and cross-instance monitoring.

## 7. Required and Recommended Follow-Up

Required before multi-worker or distributed production:

1. Implement a shared atomic replay protector, preferably Redis with TTLs.
2. Add managed signing-key rotation with key identifiers and overlap windows.
3. Connect audit events to a durable monitored sink.

Recommended:

- Add rate limits and anomaly alerts at the ingress boundary.
- Add explicit capability audience metadata before internal operational tools.
- Validate privacy filters whenever new logging handlers are registered.
- Run flagged live adversarial tests against each enabled model provider.

## 8. Test Evidence

- Focused Stage 11 suite: 167 passed.
- Both security-first and tools-first import orders: passed.
- Complete backend suite: 1,325 passed and 3 skipped in 14.56 seconds.
- Overall backend coverage: 96%.
- Python compilation: passed.
- `git diff --check`: passed.

## 9. Compatibility

Stage 9 orchestration, providers, Stage 10 business tools, database models,
Alembic migrations, and public request/response schemas are unchanged by this
review. The JTI-bearing credential format introduced in Stage 11.7.1 remains an
intentional authentication compatibility boundary: legacy tokens are rejected.

## 10. Final Decision

**PASS WITH REQUIRED FOLLOW-UP.**

The security boundaries are internally consistent and suitable for controlled
single-process deployment. Shared replay state and production-grade audit/key
operations are mandatory before scaling to multiple workers or hosts.
