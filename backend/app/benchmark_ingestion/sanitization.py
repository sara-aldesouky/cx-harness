"""Central privacy boundary for report-facing benchmark artifacts."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

from app.benchmark_ingestion.errors import IngestionSanitizationError


_SENSITIVE_KEY = re.compile(
    r"(?:password|secret|api[_-]?key|access[_-]?token|authorization|credential|"
    r"database[_-]?url|customer[_-]?id|phone|email|address)", re.I
)
_RAW_ORDER = re.compile(r"\b(?:ORD-\d+|CX-[A-Z0-9]+(?:-[A-Z0-9]+)+)\b", re.I)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s()-]{8,}\d(?!\w)")
_URL_WITH_CREDENTIALS = re.compile(r"\b(?:postgres(?:ql)?|mysql|redis)://[^\s]+", re.I)


def sanitize_text(value: str) -> str:
    """Reject unsafe free text rather than guessing at destructive redaction."""
    if _EMAIL.search(value):
        raise IngestionSanitizationError("report metadata contains an email address")
    if _PHONE.search(value):
        raise IngestionSanitizationError("report metadata contains a phone number")
    if _URL_WITH_CREDENTIALS.search(value):
        raise IngestionSanitizationError("report metadata contains a database URL")
    if _RAW_ORDER.search(value) and "*" not in value:
        raise IngestionSanitizationError("report metadata contains an unmasked order reference")
    return value


def sanitize_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-copy and validate nested report metadata."""
    copied = deepcopy(dict(value))

    def inspect(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if _SENSITIVE_KEY.search(str(key)) and str(key).lower() != "authorization_passed":
                    raise IngestionSanitizationError("report metadata contains a prohibited field")
                inspect(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                inspect(nested)
        elif isinstance(item, str):
            sanitize_text(item)

    inspect(copied)
    return copied
