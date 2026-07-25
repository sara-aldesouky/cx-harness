"""Centralized redaction and size limiting for stored audit payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


REDACTED_MARKER = "[REDACTED]"
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "secret",
        "card_number",
        "cvv",
        "phone",
        "email",
        "address",
    }
)


@dataclass(frozen=True)
class SanitizedAuditPayload:
    """A safe JSON payload and explicit truncation metadata."""

    payload: dict[str, object]
    truncated: bool
    original_size_bytes: int


def sanitize_audit_payload(
    payload: dict[str, object], max_bytes: int
) -> SanitizedAuditPayload:
    """Redact recursively, then replace oversized JSON with valid metadata."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    redacted = _redact(payload)
    serialized = json.dumps(
        redacted,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    size = len(serialized)
    if size <= max_bytes:
        return SanitizedAuditPayload(redacted, False, size)
    return SanitizedAuditPayload(
        {
            "_truncated": True,
            "_original_size_bytes": size,
        },
        True,
        size,
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                REDACTED_MARKER
                if str(key).casefold() in SENSITIVE_KEYS
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value
