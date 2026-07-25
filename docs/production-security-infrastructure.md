# Production Security Infrastructure

## Deployment architecture

The completed security layers continue to consume provider-neutral contracts:

```text
Authentication
  -> SigningKeyProvider
  -> TokenReplayProtector
       -> InMemoryTokenReplayProtector (development)
       -> DistributedTokenReplayProtector
            -> DistributedTokenReplayStore
                 -> RedisTokenReplayStore (production adapter)

SecurityAuditRecorder
  -> LoggingSecurityAuditSink (development)
  -> QueueSecurityAuditSink
  -> SIEMSecurityAuditSink
```

Authentication never imports Redis, cloud KMS, Vault, queue, or SIEM SDKs.
Concrete clients are constructed at the deployment composition boundary and
injected through these contracts.

## Distributed replay storage

`DistributedTokenReplayStore` exposes two atomic operations: check-and-record
and revoke. `DistributedTokenReplayProtector` preserves the existing
`TokenReplayProtector` interface and converts credential expiration into a
store TTL.

The Redis adapter uses one Lua operation and one hash-tagged key for each token.
The key contains a SHA-256 digest of the JTI, never the raw JTI. One-time
consumption is `SET ... NX EX` inside the script; revocation atomically replaces
any prior state with `revoked` and the remaining token TTL. This gives all
workers one cluster-safe decision and lets Redis remove expired state
automatically.

If Redis is unavailable, the adapter raises to authentication, which preserves
the existing fail-closed `replay_protection_unavailable` response. Do not fall
back to independent in-memory stores in a scaled production deployment.

## Signing-key lifecycle

Credentials now include a signed key identifier (`kid`). `SigningKeyProvider`
resolves verification material without exposing KMS or Vault behavior to the
authenticator.

Rotation lifecycle:

1. Provision a new key and make it active for issuance.
2. Retain the prior key as verification-only.
3. Set its `verify_until` after the maximum lifetime of already issued tokens.
4. Remove or disable it after that time.
5. Reject unknown, not-yet-valid, and retired keys safely.

`InMemorySigningKeyProvider` models active and previous keys for development.
AWS KMS, Google Cloud KMS, Azure Key Vault, and HashiCorp Vault integrations
should implement the same provider contract. Cache only public/verification
material or protected secret handles according to the selected signing
algorithm, and define explicit behavior during KMS outages. Key-provider
failure maps to a safe service-unavailable authentication result.

## Audit pipeline

All sinks implement `SecurityAuditSink`:

- Logging sink emits structured JSON for development.
- Queue sink publishes JSON-safe mappings using a non-blocking injected queue.
- SIEM sink invokes a vendor-neutral transport callable.

The recorder still pseudonymizes identifiers before sink invocation. Transport
exceptions trigger the safe fallback audit event and never alter business or
security decisions. Production queues should be bounded, monitored, encrypted,
and configured with a dead-letter queue. SIEM delivery should use batching,
backpressure outside request execution, and immutable retention controls.

## High availability

- Deploy Redis in a replicated configuration with persistence appropriate to
  the threat model and monitor latency, failover, evictions, and script errors.
- Configure `maxmemory-policy noeviction` or reserve enough capacity so live
  revocation markers cannot disappear early.
- Use health checks that distinguish application readiness from dependency
  degradation. Replay dependency failure must continue to fail authentication
  closed.
- Keep application instances stateless apart from explicitly documented local
  caches.
- Centralize secrets and signing-key metadata; never bake them into images.

## Disaster recovery

- Losing replay state can re-enable a copied token until its normal expiry.
  Use short token lifetimes, Redis persistence where required, tested backups,
  and an emergency signing-key rotation procedure.
- Document global token invalidation by retiring the affected signing key.
- Queue/SIEM delivery needs retention, dead-letter replay, and duplicate-safe
  event ingestion.
- Regularly test restore, regional failover, key compromise, audit backlog, and
  Redis loss scenarios.

## Deployment profiles

### Single process

The bounded in-memory replay protector and logging audit sink remain supported.

### Multi-worker and horizontally scaled

Inject one shared `DistributedTokenReplayProtector` backed by Redis or another
atomic store into every authenticator. Use a shared key provider and queue/SIEM
audit sink. Never create independent per-worker replay stores.

### Distributed

Use regional shared replay state or a deliberately documented global strategy,
managed signing keys, centralized audit ingestion, encrypted transport,
monitoring, and tested disaster recovery.

## Remaining limitations

- A concrete Redis connection factory and credentials are deployment concerns;
  this repository intentionally accepts an injected Redis-compatible client.
- Cloud KMS/Vault SDK adapters are not included.
- Queue durability, retry, and backpressure belong to infrastructure workers,
  not customer request execution.
- Key issuance, logout, and administrative revocation endpoints remain outside
  this milestone.
