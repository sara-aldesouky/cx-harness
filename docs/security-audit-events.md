# Security Audit Events

Stage 11.6 adds a provider-independent, observational security audit layer. It
does not change authentication, authorization, privacy, business execution, or
provider behavior.

## Lifecycle

Security events are emitted at existing boundaries:

1. Authentication success or failure.
2. Role-policy decisions.
3. Exact-tool authorization decisions.
4. Ownership denials and impersonation attempts.
5. Prompt, tool-output, and final-response privacy protection.
6. Policy or authorization subsystem failures.

The recorder catches every sink failure. Business requests continue, and a
minimal `audit_subsystem_failed` event is sent to an independent fallback sink
when possible.

## Event schema

Every immutable event includes timestamp, event type, severity, result,
category, optional trusted role, exact tool identity, capabilities, correlation
and request pseudonyms, customer and session pseudonyms, and a stable failure
reason code.

Raw customer UUIDs, conversation/session identifiers, names, email, phone,
addresses, payment identifiers, credentials, tokens, API keys, payloads,
exception objects, and free-form diagnostic messages are not fields in the
schema.

## Pseudonyms

Identifiers use HMAC-SHA256 with `SECURITY_AUDIT_PSEUDONYM_KEY`. The same input
and deployment key produce a stable `psn_…` value suitable for correlation,
while the source identifier cannot be recovered from the event. The audit key
must be separate from authentication credentials and at least 32 characters.
Missing or invalid production configuration emits a safe configuration event;
the process bootstrap key prevents raw identifiers from being exposed.

## Severity

- `INFO`: successful authentication and privacy protection.
- `WARNING`: expected denials, invalid credentials, and suspicious repetition.
- `ERROR`: policy, authorization, or security configuration failures.
- `CRITICAL`: audit subsystem failure.

## Repeated failures

The in-memory tracker is bounded to 10,000 pseudonymous subjects. A third
failure emits one suspicious-repetition event. It stores no source identifier
or customer payload. Distributed aggregation belongs in a future SIEM.

## Future integrations

`SecurityAuditSink` can be implemented by a SIEM, append-only compliance store,
or observability exporter without changing security or business components.
This stage intentionally adds no database table, persistence write, network
client, or provider dependency.
