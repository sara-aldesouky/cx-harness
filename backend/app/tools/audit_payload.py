"""Centralized redaction and size limiting for stored audit payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from app.data_protection import ProtectionMode, privacy_service


REDACTED_MARKER = privacy_service.rules.redacted_marker


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

    redacted = privacy_service.protect_mapping(
        payload, mode=ProtectionMode.REDACT
    )
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
