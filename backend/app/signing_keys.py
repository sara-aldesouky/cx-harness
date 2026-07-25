"""Provider-neutral signing-key resolution and rotation contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from types import MappingProxyType
from typing import Mapping, Optional, Protocol


_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class SigningKey:
    """One opaque HMAC key with an explicit verification lifecycle."""

    key_id: str
    secret: bytes = field(repr=False)
    not_before: Optional[datetime] = None
    verify_until: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not _KEY_ID.fullmatch(self.key_id):
            raise ValueError("key_id must be a safe non-empty identifier")
        if not isinstance(self.secret, bytes) or len(self.secret) < 32:
            raise ValueError("signing key must contain at least 32 bytes")
        for value in (self.not_before, self.verify_until):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError("key lifecycle timestamps must include a timezone")
        if (
            self.not_before is not None
            and self.verify_until is not None
            and self.verify_until <= self.not_before
        ):
            raise ValueError("verify_until must follow not_before")

    def valid_for_verification(self, at_time: datetime) -> bool:
        if at_time.tzinfo is None or at_time.utcoffset() is None:
            raise ValueError("verification timestamp must include a timezone")
        instant = at_time.astimezone(timezone.utc)
        return not (
            (self.not_before is not None and instant < self.not_before)
            or (self.verify_until is not None and instant >= self.verify_until)
        )


class SigningKeyProvider(Protocol):
    """Boundary implementable by Vault, KMS, or an application key ring."""

    def active_signing_key(self, at_time: datetime) -> SigningKey: ...

    def resolve_verification_key(
        self, key_id: str, at_time: datetime
    ) -> Optional[SigningKey]: ...


class InMemorySigningKeyProvider:
    """Immutable active/previous key ring for development and tests."""

    def __init__(
        self,
        active_key: SigningKey,
        previous_keys: tuple[SigningKey, ...] = (),
    ) -> None:
        if not isinstance(active_key, SigningKey):
            raise TypeError("active_key must be a SigningKey")
        keys = (active_key,) + tuple(previous_keys)
        if any(not isinstance(key, SigningKey) for key in keys):
            raise TypeError("previous_keys must contain SigningKey values")
        if len({key.key_id for key in keys}) != len(keys):
            raise ValueError("signing key identifiers must be unique")
        self._active_key_id = active_key.key_id
        self._keys: Mapping[str, SigningKey] = MappingProxyType(
            {key.key_id: key for key in keys}
        )

    def active_signing_key(self, at_time: datetime) -> SigningKey:
        key = self._keys[self._active_key_id]
        if not key.valid_for_verification(at_time):
            raise RuntimeError("active signing key is outside its lifecycle")
        return key

    def resolve_verification_key(
        self, key_id: str, at_time: datetime
    ) -> Optional[SigningKey]:
        key = self._keys.get(key_id)
        return key if key is not None and key.valid_for_verification(at_time) else None
