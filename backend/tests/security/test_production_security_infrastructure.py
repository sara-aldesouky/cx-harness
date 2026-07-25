"""Multi-worker replay, key rotation, and pluggable audit sink tests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from queue import Queue
from threading import Lock
from uuid import uuid4

import pytest

from app.authentication import (
    AuthenticationError,
    AuthenticationFailureCode,
    HMACCustomerAuthenticator,
)
from app.identity_roles import PrincipalRole
from app.security_audit import (
    AuditCategory,
    AuditResult,
    AuditSeverity,
    QueueSecurityAuditSink,
    SIEMSecurityAuditSink,
    SecurityAuditRecorder,
    SecurityEventType,
)
from app.signing_keys import InMemorySigningKeyProvider, SigningKey
from app.token_replay import (
    DistributedTokenReplayProtector,
    RedisTokenReplayStore,
    TokenUsagePolicy,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
OLD_SECRET = b"old-production-signing-key-at-least-32-bytes"
NEW_SECRET = b"new-production-signing-key-at-least-32-bytes"


class AtomicFakeRedis:
    """One shared atomic state surface used by simulated workers."""

    def __init__(self):
        self.values = {}
        self.calls = []
        self.lock = Lock()

    def eval(self, script, numkeys, *args):
        key, ttl = args[0], int(args[1])
        with self.lock:
            self.calls.append((numkeys, args))
            if "ARGV[2]" not in script:
                self.values[key] = ("revoked", ttl)
                return 1
            policy = args[2]
            state = self.values.get(key, (None, None))[0]
            if state == "revoked":
                return b"revoked"
            if policy == "session":
                return b"allowed"
            if state == "consumed":
                return b"replayed"
            self.values[key] = ("consumed", ttl)
            return b"allowed"


def provider(*, retire_old_at=NOW + timedelta(hours=1)):
    return InMemorySigningKeyProvider(
        SigningKey("new-2026-07", NEW_SECRET),
        (
            SigningKey(
                "old-2026-06", OLD_SECRET, verify_until=retire_old_at
            ),
        ),
    )


def credential(key_id, secret, token_id, policy=TokenUsagePolicy.SESSION):
    payload = ".".join(
        (
            key_id,
            str(uuid4()),
            PrincipalRole.CUSTOMER.value,
            str(int((NOW - timedelta(minutes=1)).timestamp())),
            str(int((NOW + timedelta(minutes=15)).timestamp())),
            str(token_id),
            policy.value,
        )
    )
    signature = hmac.new(secret, payload.encode(), sha256).hexdigest()
    return f"Bearer {payload}.{signature}"


def worker(shared_client, key_provider=None):
    return HMACCustomerAuthenticator(
        signing_key_provider=key_provider or provider(),
        clock=lambda: NOW,
        replay_protector=DistributedTokenReplayProtector(
            RedisTokenReplayStore(shared_client), clock=lambda: NOW
        ),
    )


def test_one_time_consumption_is_atomic_across_workers() -> None:
    redis = AtomicFakeRedis()
    token = credential(
        "new-2026-07", NEW_SECRET, uuid4(), TokenUsagePolicy.ONE_TIME
    )

    def authenticate(index):
        try:
            worker(redis).authenticate(token)
            return "allowed"
        except AuthenticationError as error:
            return error.code.value

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(authenticate, range(16)))
    assert results.count("allowed") == 1
    assert results.count("token_replay_detected") == 15


def test_revocation_is_visible_to_every_worker_and_jti_is_hashed() -> None:
    redis = AtomicFakeRedis()
    token_id = uuid4()
    expiry = NOW + timedelta(minutes=15)
    workers = [worker(redis) for _ in range(4)]
    workers[0]._replay_protector.revoke(str(token_id), expiry)
    token = credential("new-2026-07", NEW_SECRET, token_id)
    for verifier in workers:
        with pytest.raises(AuthenticationError) as caught:
            verifier.authenticate(token)
        assert caught.value.code is AuthenticationFailureCode.TOKEN_REVOKED
    assert all(str(token_id) not in key for key in redis.values)
    assert all(ttl == 900 for _, ttl in redis.values.values())


def test_concurrent_revocation_is_idempotent_and_cluster_safe() -> None:
    redis = AtomicFakeRedis()
    protector = DistributedTokenReplayProtector(
        RedisTokenReplayStore(redis), clock=lambda: NOW
    )
    token_id = str(uuid4())
    expiry = NOW + timedelta(minutes=10)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: protector.revoke(token_id, expiry), range(8)))
    assert len(redis.values) == 1
    assert next(iter(redis.values.values())) == ("revoked", 600)
    assert next(iter(redis.values)).count("{") == 1


def test_rotated_active_and_previous_keys_verify_during_overlap() -> None:
    redis = AtomicFakeRedis()
    keys = provider()
    assert keys.active_signing_key(NOW).key_id == "new-2026-07"
    assert NEW_SECRET.decode() not in repr(keys.active_signing_key(NOW))
    worker(redis, keys).authenticate(
        credential("new-2026-07", NEW_SECRET, uuid4())
    )
    worker(redis, keys).authenticate(
        credential("old-2026-06", OLD_SECRET, uuid4())
    )


def test_retired_key_and_unknown_kid_fail_safely() -> None:
    redis = AtomicFakeRedis()
    retired = provider(retire_old_at=NOW)
    with pytest.raises(AuthenticationError) as caught:
        worker(redis, retired).authenticate(
            credential("old-2026-06", OLD_SECRET, uuid4())
        )
    assert caught.value.code is AuthenticationFailureCode.INVALID_SIGNING_KEY_IDENTIFIER
    assert "old-2026-06" not in str(caught.value)


def test_missing_kid_and_key_provider_outage_fail_safely() -> None:
    token_without_kid = credential("new-2026-07", NEW_SECRET, uuid4()).replace(
        "Bearer new-2026-07.", "Bearer "
    )
    with pytest.raises(AuthenticationError) as missing:
        worker(AtomicFakeRedis()).authenticate(token_without_kid)
    assert missing.value.code is AuthenticationFailureCode.MISSING_SIGNING_KEY_IDENTIFIER

    class UnavailableKeys:
        def resolve_verification_key(self, key_id, at_time):
            raise RuntimeError("vault internal endpoint and secret")

    with pytest.raises(AuthenticationError) as unavailable:
        HMACCustomerAuthenticator(
            signing_key_provider=UnavailableKeys(),
            clock=lambda: NOW,
            replay_protector=DistributedTokenReplayProtector(
                RedisTokenReplayStore(AtomicFakeRedis()), clock=lambda: NOW
            ),
        ).authenticate(credential("new-2026-07", NEW_SECRET, uuid4()))
    assert unavailable.value.code is AuthenticationFailureCode.SIGNING_KEY_UNAVAILABLE
    assert str(unavailable.value) == "Authentication is temporarily unavailable."


def test_queue_and_siem_sinks_receive_same_json_safe_contract() -> None:
    queue = Queue()
    sent = []
    queue_recorder = SecurityAuditRecorder(
        b"audit-pseudonym-key-at-least-32-bytes",
        sink=QueueSecurityAuditSink(queue),
    )
    siem_recorder = SecurityAuditRecorder(
        b"audit-pseudonym-key-at-least-32-bytes",
        sink=SIEMSecurityAuditSink(sent.append),
    )
    for recorder in (queue_recorder, siem_recorder):
        recorder.record(
            SecurityEventType.AUTHENTICATION_SUCCEEDED,
            severity=AuditSeverity.INFO,
            result=AuditResult.SUCCESS,
            category=AuditCategory.AUTHENTICATION,
            customer_id=uuid4(),
        )
    queued = queue.get_nowait()
    assert queued["event_type"] == sent[0]["event_type"] == "authentication_succeeded"
    assert queued["customer_pseudonym"].startswith("psn_")


def test_audit_transport_failure_uses_safe_fallback() -> None:
    fallback = []

    def fail(_event):
        raise RuntimeError("vendor secret transport detail")

    recorder = SecurityAuditRecorder(
        b"audit-pseudonym-key-at-least-32-bytes",
        sink=SIEMSecurityAuditSink(fail),
        fallback_sink=SIEMSecurityAuditSink(fallback.append),
    )
    recorder.record(
        SecurityEventType.AUTHENTICATION_SUCCEEDED,
        severity=AuditSeverity.INFO,
        result=AuditResult.SUCCESS,
        category=AuditCategory.AUTHENTICATION,
    )
    assert fallback[0]["event_type"] == "audit_subsystem_failed"
    assert "vendor" not in str(fallback[0])
