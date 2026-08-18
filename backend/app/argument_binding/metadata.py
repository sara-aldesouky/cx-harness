"""Bounded immutable metadata accepted by trusted execution contracts."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


EXTENSION_MAX_COUNT = 32
EXTENSION_MAX_KEY_LENGTH = 64
EXTENSION_MAX_STRING_LENGTH = 4096
EXTENSION_MAX_COLLECTION_LENGTH = 64
EXTENSION_MAX_NESTING_DEPTH = 6
EXTENSION_MAX_SERIALIZED_BYTES = 16_384
EXTENSION_MAX_INTEGER_ABS = 9_007_199_254_740_991
EXTENSION_MAX_FLOAT_ABS = 1.0e308

EXTENSION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

RESERVED_EXTENSION_NAMES = frozenset(
    {
        "customer_id",
        "conversation_id",
        "order_number",
        "tool_name",
        "call_id",
        "authorization",
        "authorized",
        "authorization_granted",
        "approval",
        "approval_token",
        "idempotency_key",
        "actor_id",
        "tenant_id",
        "user_id",
        "account_id",
        "refund_limit",
        "bypass",
        "bypass_verification",
        "permissions",
        "roles",
        "scopes",
    }
)

RESERVED_EXTENSION_PREFIXES = (
    "auth_",
    "authorization_",
    "identity_",
    "permission_",
    "role_",
    "scope_",
    "trusted_",
    "protected_",
    "system_",
    "internal_",
)


def freeze_extension_metadata(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and defensively freeze non-authoritative JSON metadata."""

    if not isinstance(value, Mapping):
        raise TypeError("extensions must be a mapping")
    if len(value) > EXTENSION_MAX_COUNT:
        raise ValueError("extensions exceed the maximum entry count")
    normalized = _freeze_mapping(value, depth=0)
    encoded = json.dumps(
        _mutable_copy(normalized),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > EXTENSION_MAX_SERIALIZED_BYTES:
        raise ValueError("extensions exceed the maximum serialized size")
    return normalized


def extension_metadata_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return JSON containers from validated immutable metadata."""

    return _mutable_copy(value)


def _freeze_mapping(value: Mapping[str, Any], *, depth: int) -> Mapping[str, Any]:
    _check_depth(depth)
    if len(value) > EXTENSION_MAX_COLLECTION_LENGTH:
        raise ValueError("extension mapping exceeds the maximum length")
    items: dict[str, Any] = {}
    normalized_seen: set[str] = set()
    for raw_key, raw_value in value.items():
        key = _validate_key(raw_key)
        normalized = key.casefold()
        if normalized in normalized_seen:
            raise ValueError("extension keys must be unique after normalization")
        normalized_seen.add(normalized)
        items[key] = _freeze_value(raw_value, depth=depth + 1)
    return MappingProxyType(dict(sorted(items.items())))


def _validate_key(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("extension keys must be strings")
    if value != value.strip():
        raise ValueError("extension keys must not contain surrounding whitespace")
    if not value:
        raise ValueError("extension keys must not be empty")
    if len(value) > EXTENSION_MAX_KEY_LENGTH or not EXTENSION_KEY_PATTERN.fullmatch(value):
        raise ValueError("extension keys must use lowercase snake_case")
    normalized = value.casefold()
    if normalized in RESERVED_EXTENSION_NAMES or normalized.startswith(
        RESERVED_EXTENSION_PREFIXES
    ):
        raise ValueError("extension key is reserved")
    return value


def _freeze_value(value: Any, *, depth: int) -> Any:
    _check_depth(depth)
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str) and len(value) > EXTENSION_MAX_STRING_LENGTH:
            raise ValueError("extension string exceeds the maximum length")
        return value
    if isinstance(value, int):
        if abs(value) > EXTENSION_MAX_INTEGER_ABS:
            raise ValueError("extension integer exceeds the permitted range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > EXTENSION_MAX_FLOAT_ABS:
            raise ValueError("extension float must be finite and bounded")
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping(value, depth=depth)
    if isinstance(value, (list, tuple)):
        if len(value) > EXTENSION_MAX_COLLECTION_LENGTH:
            raise ValueError("extension sequence exceeds the maximum length")
        return tuple(_freeze_value(item, depth=depth + 1) for item in value)
    raise ValueError("extension values must be immutable JSON-compatible metadata")


def _check_depth(depth: int) -> None:
    if depth > EXTENSION_MAX_NESTING_DEPTH:
        raise ValueError("extensions exceed the maximum nesting depth")


def _mutable_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_mutable_copy(item) for item in value]
    return value
