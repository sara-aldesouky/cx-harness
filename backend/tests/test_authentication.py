"""Pure unit tests for trusted customer authentication."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.authentication import (
    AuthenticationError,
    AuthenticationFailureCode,
    HMACCustomerAuthenticator,
    TrustedCustomerIdentity,
)
from app.role_policy import PrincipalRole
from app.token_replay import InMemoryTokenReplayProtector, TokenUsagePolicy


SECRET = "stage-11-test-secret-with-at-least-32-characters"
NOW = datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc)


def token(customer_id, expires_at: datetime, secret: str = SECRET) -> str:
    issued_at = NOW - timedelta(minutes=1)
    token_id = uuid4()
    role = PrincipalRole.CUSTOMER.value
    usage = TokenUsagePolicy.SESSION.value
    issued = int(issued_at.timestamp())
    expiry = int(expires_at.timestamp())
    payload = f"default.{customer_id}.{role}.{issued}.{expiry}.{token_id}.{usage}"
    signature = hmac.new(secret.encode(), payload.encode(), sha256).hexdigest()
    return f"Bearer {payload}.{signature}"


def authenticator(secret: str = SECRET) -> HMACCustomerAuthenticator:
    return HMACCustomerAuthenticator(
        secret,
        clock=lambda: NOW,
        replay_protector=InMemoryTokenReplayProtector(clock=lambda: NOW),
    )


def test_successful_authentication_returns_immutable_trusted_identity() -> None:
    customer_id = uuid4()
    result = authenticator().authenticate(
        token(customer_id, NOW + timedelta(minutes=15))
    )

    assert result.customer_id == customer_id
    assert result.role is PrincipalRole.CUSTOMER
    assert result.authenticated_at == NOW
    assert result.authentication_method == "hmac_bearer"
    assert result.model_dump(mode="json")["customer_id"] == str(customer_id)
    with pytest.raises(ValidationError):
        result.customer_id = uuid4()  # type: ignore[misc]


def test_missing_identity_is_structured() -> None:
    with pytest.raises(AuthenticationError) as caught:
        authenticator().authenticate(None)
    assert caught.value.code is AuthenticationFailureCode.MISSING_IDENTITY


@pytest.mark.parametrize(
    "credential",
    ["Basic abc", "Bearer malformed"],
)
def test_invalid_identity_is_structured(credential: str) -> None:
    with pytest.raises(AuthenticationError) as caught:
        authenticator().authenticate(credential)
    assert caught.value.code is AuthenticationFailureCode.INVALID_IDENTITY


def test_legacy_credential_without_jti_is_rejected() -> None:
    with pytest.raises(AuthenticationError) as caught:
        authenticator().authenticate("Bearer invalid.123.signature")
    assert caught.value.code is AuthenticationFailureCode.MISSING_TOKEN_IDENTIFIER


def test_tampered_customer_identity_is_rejected() -> None:
    original = uuid4()
    credential = token(original, NOW + timedelta(minutes=15))
    tampered = credential.replace(str(original), str(uuid4()))

    with pytest.raises(AuthenticationError) as caught:
        authenticator().authenticate(tampered)
    assert caught.value.code is AuthenticationFailureCode.INVALID_IDENTITY


def test_expired_authentication_is_structured() -> None:
    with pytest.raises(AuthenticationError) as caught:
        authenticator().authenticate(token(uuid4(), NOW))
    assert caught.value.code is AuthenticationFailureCode.EXPIRED_AUTHENTICATION


@pytest.mark.parametrize("secret", ["", "too-short"])
def test_invalid_configuration_is_authentication_unavailable(secret: str) -> None:
    with pytest.raises(AuthenticationError) as caught:
        authenticator(secret)
    assert caught.value.code is AuthenticationFailureCode.AUTHENTICATION_UNAVAILABLE


def test_trusted_identity_rejects_invalid_lifecycle() -> None:
    with pytest.raises(ValidationError):
        TrustedCustomerIdentity(
            customer_id=uuid4(),
            authenticated_at=NOW,
            expires_at=NOW,
            authentication_method="hmac_bearer",
        )
