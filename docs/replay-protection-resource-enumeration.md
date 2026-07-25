# Stage 11.7.1 — Replay Protection and Resource Enumeration Resistance

## Threat model

Two accepted Stage 11 controls had residual risks. A valid HMAC bearer token
could be copied and reused until expiration, and protected-resource outcomes
could distinguish an object owned by somebody else from an object that did not
exist. The first enables credential replay; the second enables identifier
enumeration.

This hardening remains between the existing authentication, ownership,
privacy, and audit boundaries. It does not alter providers, orchestration, or
business tools.

## Replay-protection architecture

The signed credential payload now contains:

- signing-key identifier (`kid`)
- subject/customer UUID
- trusted role
- issued-at Unix timestamp
- expiration Unix timestamp
- UUID token identifier (`jti`)
- usage policy (`session` or `one_time`)
- HMAC-SHA256 signature

Authentication resolves the verification key through `SigningKeyProvider`, then
verifies the signature, timestamps, role, JTI, and usage policy before producing
trusted identity. It then consults `TokenReplayProtector`.
Missing or malformed JTIs fail with safe 401 responses. Store unavailability
fails closed with a safe 503 response.

### Replay policy

Short-lived `session` tokens may be reused until expiration. Explicit
revocation—such as future logout or security invalidation—blocks subsequent
use. `one_time` tokens are atomically consumed on first use and all later uses
are rejected as replay attempts.

The development implementation is thread-safe and in-memory. It cleans expired
revocation and consumption entries during operations and has a fixed capacity.
It never evicts a still-valid security marker: capacity exhaustion fails closed
instead. This prevents bounded storage from silently re-enabling a token.

No logout endpoint is introduced. Trusted callers can use the replay protector's
revocation contract until account-management endpoints are designed.

### Future centralized storage

Production multi-instance deployment requires an atomic shared implementation,
normally Redis or a database. It must implement the same check-and-record and
revocation contract, use TTLs matching token expiry, and provide atomic
one-time consumption. The in-memory implementation is process-local and is not
sufficient across multiple workers or hosts.

## Resource-enumeration resistance

The ownership resolver retains three internal results: `owned`, `not_owned`,
and `not_found`. Protected transactional requests now stop before tool
construction, invocation, repository-backed business execution, and ToolCall
creation for both `not_owned` and `not_found`.

Internal authorization and security audit paths retain precise reason codes:

- `unauthorized_resource` for ownership mismatch
- `resource_not_found` for absence

The model/tool-result and HTTP boundaries normalize both to the same public
shape:

```json
{
  "code": "resource_not_found",
  "message": "The requested resource was not found."
}
```

The HTTP status is 404. Raw resource identifiers, ownership state, customer
identity, and database details are not returned. Customer profile mismatch is
normalized through the same external boundary. Order-scoped delivery, payment,
and refund capabilities inherit this behavior from the shared ownership
resolver. Public Knowledge remains outside ownership authorization.

## Audit and privacy behavior

Replay events record only stable reason codes and existing pseudonymous request,
session, and customer correlations. Raw bearer tokens and raw JTIs never enter
audit events. Audit sink failure remains best-effort and cannot change an
authentication or authorization decision.

## Remaining limitations

- The in-memory replay store is local to one Python process.
- Credential issuance and logout endpoints remain external to this stage.
- Distributed deployments require shared atomic replay state.
- Rate limiting and behavioral anomaly detection remain separate controls.
- Generic 404 responses reduce semantic detail for customers by design.
