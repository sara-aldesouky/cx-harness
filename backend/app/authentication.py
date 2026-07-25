"""Provider-independent customer authentication contracts and HMAC verifier."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import hmac
from typing import Callable, Optional, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.identity_roles import PrincipalRole
from app.signing_keys import (
    InMemorySigningKeyProvider,
    SigningKey,
    SigningKeyProvider,
)
from app.token_replay import (
    TokenReplayDecision,
    TokenReplayProtector,
    TokenUsagePolicy,
)


class AuthenticationFailureCode(str, Enum):
    """Stable, transport-neutral authentication failure identities."""

    MISSING_IDENTITY = "missing_identity"
    INVALID_IDENTITY = "invalid_identity"
    EXPIRED_AUTHENTICATION = "expired_authentication"
    AUTHENTICATION_UNAVAILABLE = "authentication_unavailable"
    MISSING_TOKEN_IDENTIFIER = "missing_token_identifier"
    INVALID_TOKEN_IDENTIFIER = "invalid_token_identifier"
    TOKEN_REVOKED = "token_revoked"
    TOKEN_REPLAY_DETECTED = "token_replay_detected"
    REPLAY_PROTECTION_UNAVAILABLE = "replay_protection_unavailable"
    MISSING_SIGNING_KEY_IDENTIFIER = "missing_signing_key_identifier"
    INVALID_SIGNING_KEY_IDENTIFIER = "invalid_signing_key_identifier"
    SIGNING_KEY_UNAVAILABLE = "signing_key_unavailable"


class AuthenticationError(RuntimeError):
    """Safe structured failure raised before trusted identity exists."""

    def __init__(self, code: AuthenticationFailureCode, public_message: str) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class TrustedCustomerIdentity(BaseModel):
    """Immutable identity produced only after credential verification.

    The object proves who the caller is. It carries no permissions, roles,
    ownership decisions, or tool authorization.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    customer_id: UUID
    authenticated_at: datetime
    expires_at: datetime
    authentication_method: str
    role: PrincipalRole = PrincipalRole.CUSTOMER

    @field_validator("authenticated_at", "expires_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authentication timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("authentication_method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("authentication_method must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "TrustedCustomerIdentity":
        if self.expires_at <= self.authenticated_at:
            raise ValueError("expires_at must be after authenticated_at")
        return self


class CustomerAuthenticator(Protocol):
    """Minimal authentication behavior required by application entry points."""

    def authenticate(self, authorization: Optional[str]) -> TrustedCustomerIdentity:
        """Validate one opaque credential and return trusted identity."""


class HMACCustomerAuthenticator:
    """Validate locally signed Bearer assertions without provider coupling.

    The signed payload contains subject, trusted role, issued-at, expiry, JTI,
    and usage policy. Token issuance belongs to a trusted identity system and
    is intentionally outside this verifier.
    """

    _METHOD = "hmac_bearer"

    def __init__(
        self,
        secret: Optional[str] = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        replay_protector: Optional[TokenReplayProtector] = None,
        signing_key_provider: Optional[SigningKeyProvider] = None,
    ) -> None:
        if signing_key_provider is not None and secret is not None:
            raise AuthenticationError(
                AuthenticationFailureCode.AUTHENTICATION_UNAVAILABLE,
                "Authentication is temporarily unavailable.",
            )
        if signing_key_provider is None:
            normalized_secret = (secret or "").strip()
            if len(normalized_secret) < 32:
                raise AuthenticationError(
                    AuthenticationFailureCode.AUTHENTICATION_UNAVAILABLE,
                    "Authentication is temporarily unavailable.",
                )
            signing_key_provider = InMemorySigningKeyProvider(
                SigningKey("default", normalized_secret.encode("utf-8"))
            )
        if not callable(
            getattr(signing_key_provider, "resolve_verification_key", None)
        ):
            raise AuthenticationError(
                AuthenticationFailureCode.AUTHENTICATION_UNAVAILABLE,
                "Authentication is temporarily unavailable.",
            )
        self._signing_keys = signing_key_provider
        self._clock = clock
        self._replay_protector = replay_protector

    def authenticate(self, authorization: Optional[str]) -> TrustedCustomerIdentity:
        """Verify scheme, identity, expiry, and signature in constant time."""

        if authorization is None or not authorization.strip():
            raise AuthenticationError(
                AuthenticationFailureCode.MISSING_IDENTITY,
                "Authentication credentials are required.",
            )
        scheme, separator, token = authorization.strip().partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            self._invalid()

        parts = token.strip().split(".")
        if len(parts) == 3:
            raise AuthenticationError(
                AuthenticationFailureCode.MISSING_TOKEN_IDENTIFIER,
                "Authentication credentials are invalid.",
            )
        if len(parts) == 7:
            raise AuthenticationError(
                AuthenticationFailureCode.MISSING_SIGNING_KEY_IDENTIFIER,
                "Authentication credentials are invalid.",
            )
        if len(parts) != 8:
            self._invalid()
        (
            key_id,
            customer_text,
            role_text,
            issued_text,
            expiry_text,
            token_identifier_text,
            usage_text,
            supplied_signature,
        ) = parts
        if not key_id or len(key_id) > 64 or not all(
            character.isalnum() or character in "_-" for character in key_id
        ):
            raise AuthenticationError(
                AuthenticationFailureCode.INVALID_SIGNING_KEY_IDENTIFIER,
                "Authentication credentials are invalid.",
            )
        try:
            customer_id = UUID(customer_text)
            role = PrincipalRole(role_text)
            issued_seconds = int(issued_text)
            expiry_seconds = int(expiry_text)
        except (TypeError, ValueError, AttributeError):
            self._invalid()

        try:
            token_identifier = str(UUID(token_identifier_text))
        except (TypeError, ValueError, AttributeError):
            raise AuthenticationError(
                AuthenticationFailureCode.INVALID_TOKEN_IDENTIFIER,
                "Authentication credentials are invalid.",
            )
        try:
            usage_policy = TokenUsagePolicy(usage_text)
        except ValueError:
            self._invalid()

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise AuthenticationError(
                AuthenticationFailureCode.AUTHENTICATION_UNAVAILABLE,
                "Authentication is temporarily unavailable.",
            )
        now = now.astimezone(timezone.utc)
        try:
            verification_key = self._signing_keys.resolve_verification_key(
                key_id, now
            )
        except Exception as error:
            raise AuthenticationError(
                AuthenticationFailureCode.SIGNING_KEY_UNAVAILABLE,
                "Authentication is temporarily unavailable.",
            ) from error
        if verification_key is None:
            raise AuthenticationError(
                AuthenticationFailureCode.INVALID_SIGNING_KEY_IDENTIFIER,
                "Authentication credentials are invalid.",
            )

        signed_payload = (
            f"{key_id}.{customer_id}.{role.value}.{issued_seconds}.{expiry_seconds}."
            f"{token_identifier}.{usage_policy.value}"
        ).encode("utf-8")
        expected_signature = hmac.new(
            verification_key.secret, signed_payload, sha256
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            self._invalid()

        expires_at = datetime.fromtimestamp(expiry_seconds, tz=timezone.utc)
        issued_at = datetime.fromtimestamp(issued_seconds, tz=timezone.utc)
        if expires_at <= now:
            raise AuthenticationError(
                AuthenticationFailureCode.EXPIRED_AUTHENTICATION,
                "Authentication credentials have expired.",
            )
        if issued_at > now or issued_at >= expires_at:
            self._invalid()
        if self._replay_protector is None:
            raise AuthenticationError(
                AuthenticationFailureCode.REPLAY_PROTECTION_UNAVAILABLE,
                "Authentication is temporarily unavailable.",
            )
        try:
            decision = self._replay_protector.check_and_record(
                token_identifier, expires_at, usage_policy
            )
        except Exception as error:
            raise AuthenticationError(
                AuthenticationFailureCode.REPLAY_PROTECTION_UNAVAILABLE,
                "Authentication is temporarily unavailable.",
            ) from error
        if decision is TokenReplayDecision.REVOKED:
            raise AuthenticationError(
                AuthenticationFailureCode.TOKEN_REVOKED,
                "Authentication credentials are invalid.",
            )
        if decision is TokenReplayDecision.REPLAYED:
            raise AuthenticationError(
                AuthenticationFailureCode.TOKEN_REPLAY_DETECTED,
                "Authentication credentials are invalid.",
            )
        return TrustedCustomerIdentity(
            customer_id=customer_id,
            authenticated_at=now,
            expires_at=expires_at,
            authentication_method=self._METHOD,
            role=role,
        )

    @staticmethod
    def _invalid() -> None:
        raise AuthenticationError(
            AuthenticationFailureCode.INVALID_IDENTITY,
            "Authentication credentials are invalid.",
        )
