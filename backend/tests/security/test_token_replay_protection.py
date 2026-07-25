"""Focused replay-protection tests with no network or database dependency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from uuid import uuid4

import pytest

from app.authentication import (
    AuthenticationError,
    AuthenticationFailureCode,
    HMACCustomerAuthenticator,
)
from app.identity_roles import PrincipalRole
from app.token_replay import InMemoryTokenReplayProtector, TokenUsagePolicy


SECRET = "replay-protection-test-secret-at-least-32-characters"
NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def credential(
    *,
    token_id=None,
    policy=TokenUsagePolicy.SESSION,
    expires_at=NOW + timedelta(minutes=15),
    issued_at=NOW - timedelta(minutes=1),
    customer_id=None,
):
    token_id = token_id or uuid4()
    customer_id = customer_id or uuid4()
    payload = ".".join(
        (
            "default",
            str(customer_id),
            PrincipalRole.CUSTOMER.value,
            str(int(issued_at.timestamp())),
            str(int(expires_at.timestamp())),
            str(token_id),
            policy.value,
        )
    )
    signature = hmac.new(SECRET.encode(), payload.encode(), sha256).hexdigest()
    return f"Bearer {payload}.{signature}"


def authenticator(store):
    return HMACCustomerAuthenticator(
        SECRET, clock=lambda: NOW, replay_protector=store
    )


def test_valid_jti_and_normal_session_reuse_are_allowed() -> None:
    store = InMemoryTokenReplayProtector(clock=lambda: NOW)
    value = credential()
    verifier = authenticator(store)
    assert verifier.authenticate(value).customer_id == verifier.authenticate(value).customer_id
    assert store.state_size == 0


def test_missing_jti_fails_closed() -> None:
    customer = uuid4()
    expiry = int((NOW + timedelta(minutes=5)).timestamp())
    payload = f"{customer}.{expiry}"
    signature = hmac.new(SECRET.encode(), payload.encode(), sha256).hexdigest()
    with pytest.raises(AuthenticationError) as caught:
        authenticator(InMemoryTokenReplayProtector(clock=lambda: NOW)).authenticate(
            f"Bearer {payload}.{signature}"
        )
    assert caught.value.code is AuthenticationFailureCode.MISSING_TOKEN_IDENTIFIER


def test_malformed_jti_fails_closed_without_echoing_it() -> None:
    parts = credential().split(".")
    parts[5] = "raw-sensitive-jti"
    value = ".".join(parts)
    with pytest.raises(AuthenticationError) as caught:
        authenticator(InMemoryTokenReplayProtector(clock=lambda: NOW)).authenticate(value)
    assert caught.value.code in {
        AuthenticationFailureCode.INVALID_IDENTITY,
        AuthenticationFailureCode.INVALID_TOKEN_IDENTIFIER,
    }
    assert "raw-sensitive-jti" not in str(caught.value)


def test_expired_credential_is_rejected_before_replay_state() -> None:
    store = InMemoryTokenReplayProtector(clock=lambda: NOW)
    with pytest.raises(AuthenticationError) as caught:
        authenticator(store).authenticate(credential(expires_at=NOW))
    assert caught.value.code is AuthenticationFailureCode.EXPIRED_AUTHENTICATION
    assert store.state_size == 0


def test_revoked_credential_cannot_be_used() -> None:
    token_id = uuid4()
    expiry = NOW + timedelta(minutes=10)
    store = InMemoryTokenReplayProtector(clock=lambda: NOW)
    store.revoke(str(token_id), expiry)
    with pytest.raises(AuthenticationError) as caught:
        authenticator(store).authenticate(credential(token_id=token_id, expires_at=expiry))
    assert caught.value.code is AuthenticationFailureCode.TOKEN_REVOKED
    assert str(token_id) not in str(caught.value)


def test_one_time_credential_is_consumed_exactly_once() -> None:
    store = InMemoryTokenReplayProtector(clock=lambda: NOW)
    verifier = authenticator(store)
    value = credential(policy=TokenUsagePolicy.ONE_TIME)
    verifier.authenticate(value)
    with pytest.raises(AuthenticationError) as caught:
        verifier.authenticate(value)
    assert caught.value.code is AuthenticationFailureCode.TOKEN_REPLAY_DETECTED


def test_concurrent_one_time_replay_has_exactly_one_success() -> None:
    store = InMemoryTokenReplayProtector(clock=lambda: NOW)
    verifier = authenticator(store)
    value = credential(policy=TokenUsagePolicy.ONE_TIME)

    def attempt():
        try:
            verifier.authenticate(value)
            return "allowed"
        except AuthenticationError as error:
            return error.code.value

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: attempt(), range(8)))
    assert results.count("allowed") == 1
    assert results.count("token_replay_detected") == 7


def test_expired_state_cleanup_and_bounded_storage() -> None:
    clock = [NOW]
    store = InMemoryTokenReplayProtector(max_entries=2, clock=lambda: clock[0])
    for offset in (1, 2):
        store.revoke(str(uuid4()), NOW + timedelta(minutes=offset))
    assert store.state_size == 2
    with pytest.raises(RuntimeError, match="capacity exhausted"):
        store.revoke(str(uuid4()), NOW + timedelta(minutes=3))
    assert store.state_size == 2
    clock[0] = NOW + timedelta(minutes=4)
    assert store.state_size == 0


class FailingStore:
    def check_and_record(self, *args, **kwargs):
        raise RuntimeError("raw-jti-or-store-detail")


def test_replay_store_failure_is_safe_and_fails_closed() -> None:
    with pytest.raises(AuthenticationError) as caught:
        authenticator(FailingStore()).authenticate(credential())
    assert caught.value.code is AuthenticationFailureCode.REPLAY_PROTECTION_UNAVAILABLE
    assert str(caught.value) == "Authentication is temporarily unavailable."
