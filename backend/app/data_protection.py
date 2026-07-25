"""Central provider-independent masking, redaction, and privacy utilities."""

from __future__ import annotations

import logging
import re
from hashlib import sha256
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProtectionMode(str, Enum):
    MASK = "mask"
    REDACT = "redact"


class PrivacyRules(BaseModel):
    """Immutable configurable field classifications and output markers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    email_fields: frozenset[str] = frozenset({"email", "email_address"})
    phone_fields: frozenset[str] = frozenset({"phone", "phone_number"})
    name_fields: frozenset[str] = frozenset(
        {"full_name", "display_name", "customer_name"}
    )
    address_fields: frozenset[str] = frozenset(
        {"address", "delivery_address", "billing_address"}
    )
    identifier_fields: frozenset[str] = frozenset(
        {
            "customer_id",
            "conversation_id",
            "session_id",
            "execution_id",
            "trace_id",
            "model_run_id",
            "tool_call_id",
            "order_id",
            "internal_customer_id",
            "payment_identifier",
            "payment_transaction_id",
            "processor_token",
        }
    )
    secret_fields: frozenset[str] = frozenset(
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
            "security_code",
        }
    )
    redacted_marker: str = "[REDACTED]"
    address_marker: str = "[REDACTED ADDRESS]"


DEFAULT_PRIVACY_RULES = PrivacyRules()


class DataProtectionService:
    """Create safe provider, response, logging, metric, and audit projections.

    Original trusted objects are never mutated. Internal identifiers remain
    available to authentication, ownership checks, and repositories, while
    only protected copies cross untrusted presentation boundaries.
    """

    _EMAIL = re.compile(r"(?<![\w.+-])([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?!\w)")
    _PHONE = re.compile(r"(?<!\w)(\+?\d{2})[\d\s-]{5,}(\d{2})(?!\w)")
    _UUID = re.compile(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
    )
    _PAYMENT_NUMBER = re.compile(r"(?<!\d)(?:\d[ -]?){12,19}(?!\d)")
    _NAME_PHRASE = re.compile(
        r"(?i)\b(my name is|customer name\s*:)\s+([A-Za-z][A-Za-z'-]*)\s+([A-Za-z][A-Za-z'-]*)"
    )
    _ADDRESS_PHRASE = re.compile(
        r"(?i)\b(my (?:delivery )?address is|delivery address\s*:)\s*([^\n.!?]+)"
    )
    _SECRET_ASSIGNMENT = re.compile(
        r"(?i)\b(password|api[_ -]?key|access[_ -]?token|authorization)\s*[:=]\s*\S+"
    )

    def __init__(self, rules: PrivacyRules = DEFAULT_PRIVACY_RULES) -> None:
        if not isinstance(rules, PrivacyRules):
            raise TypeError("rules must be PrivacyRules")
        self.rules = rules

    def protect_mapping(
        self, value: Mapping[str, Any], *, mode: ProtectionMode = ProtectionMode.MASK
    ) -> dict[str, Any]:
        """Recursively protect structured data using centralized field classes."""

        if not isinstance(value, Mapping):
            raise TypeError("value must be a mapping")
        return {
            str(key): self._protect_field(str(key), item, mode)
            for key, item in value.items()
        }

    def protect_message_input(self, value: Any) -> Any:
        """Return a protected copy of a conversation message or mapping."""

        if isinstance(value, BaseModel) and hasattr(value, "content"):
            return value.model_copy(
                update={"content": self.protect_text(str(value.content))}
            )
        if isinstance(value, Mapping):
            copied = dict(value)
            content = copied.get("content")
            if isinstance(content, str):
                copied["content"] = self.protect_text(content)
            metadata = copied.get("metadata")
            if isinstance(metadata, Mapping):
                copied["metadata"] = self.protect_mapping(metadata)
            return copied
        raise TypeError("message must be a validated model or mapping")

    def protect_text(self, value: str) -> str:
        """Mask common PII and secrets in unstructured prompt/output text."""

        if not isinstance(value, str):
            raise TypeError("value must be a string")
        protected = self._SECRET_ASSIGNMENT.sub(
            lambda match: f"{match.group(1)}={self.rules.redacted_marker}", value
        )
        protected = self._EMAIL.sub(
            lambda match: f"{match.group(1)}***@{match.group(2)}", protected
        )
        protected = self._PHONE.sub(
            lambda match: f"{match.group(1)}********{match.group(2)}", protected
        )
        protected = self._PAYMENT_NUMBER.sub(self.rules.redacted_marker, protected)
        protected = self._UUID.sub(self.rules.redacted_marker, protected)
        protected = self._NAME_PHRASE.sub(
            lambda match: (
                f"{match.group(1)} {self.mask_name(match.group(2) + ' ' + match.group(3))}"
            ),
            protected,
        )
        return self._ADDRESS_PHRASE.sub(
            lambda match: f"{match.group(1)} {self.rules.address_marker}",
            protected,
        )

    def protect_error(self, value: object) -> str:
        """Return a safe message without SQL, stack, URL, or identifier detail."""

        text = self.protect_text(str(value))
        unsafe_markers = (
            "traceback",
            "sqlalchemy",
            "postgresql://",
            "database_url",
            "select ",
            "insert ",
            "update ",
            "delete ",
        )
        if any(marker in text.casefold() for marker in unsafe_markers):
            return "The operation could not be completed safely."
        return text

    def protect_log_text(self, value: str) -> str:
        """Pseudonymize correlation UUIDs while masking all other log PII."""

        pseudonymized = self._UUID.sub(
            lambda match: f"id_{sha256(match.group(0).lower().encode()).hexdigest()[:12]}",
            value,
        )
        return self.protect_text(pseudonymized)

    @staticmethod
    def mask_name(value: str) -> str:
        return " ".join(
            part[:1] + "*" * max(3, len(part) - 1)
            for part in value.strip().split()
        )

    @staticmethod
    def mask_email(value: str) -> str:
        local, separator, domain = value.strip().partition("@")
        if not separator or not local or not domain:
            return "[REDACTED]"
        return f"{local[0]}***@{domain}"

    @staticmethod
    def mask_phone(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        prefix = "+" if value.strip().startswith("+") else ""
        if len(digits) < 6:
            return "[REDACTED]"
        return f"{prefix}{digits[:2]}{'*' * max(4, len(digits) - 4)}{digits[-2:]}"

    def _protect_field(
        self, key: str, value: Any, mode: ProtectionMode
    ) -> Any:
        normalized = key.casefold()
        if normalized in self.rules.secret_fields:
            return self.rules.redacted_marker
        protected_fields = (
            self.rules.email_fields
            | self.rules.phone_fields
            | self.rules.name_fields
            | self.rules.address_fields
            | self.rules.identifier_fields
        )
        if mode is ProtectionMode.REDACT and normalized in protected_fields:
            return self.rules.redacted_marker
        if normalized in self.rules.email_fields:
            return self.mask_email(str(value))
        if normalized in self.rules.phone_fields:
            return self.mask_phone(str(value))
        if normalized in self.rules.name_fields:
            return self.mask_name(str(value))
        if normalized in self.rules.address_fields:
            return self.rules.address_marker
        if normalized in self.rules.identifier_fields:
            return self.rules.redacted_marker
        if isinstance(value, Mapping):
            return self.protect_mapping(value, mode=mode)
        if isinstance(value, (list, tuple)):
            return [
                self._protect_field("", item, mode)
                if isinstance(item, Mapping)
                else self.protect_text(item) if isinstance(item, str) else item
                for item in value
            ]
        if isinstance(value, UUID):
            return self.rules.redacted_marker
        return self.protect_text(value) if isinstance(value, str) else value


class PrivacyLogFilter(logging.Filter):
    """Sanitize a fully rendered log record before any handler emits it."""

    def __init__(self, service: DataProtectionService) -> None:
        super().__init__()
        self._service = service

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._service.protect_log_text(record.getMessage())
        record.args = ()
        return True


privacy_service = DataProtectionService()


def install_privacy_log_filters() -> tuple[tuple[logging.Handler, PrivacyLogFilter], ...]:
    """Protect all currently configured root handlers for application lifetime."""

    installed = []
    for handler in logging.getLogger().handlers:
        privacy_filter = PrivacyLogFilter(privacy_service)
        handler.addFilter(privacy_filter)
        installed.append((handler, privacy_filter))
    return tuple(installed)


def remove_privacy_log_filters(
    installed: tuple[tuple[logging.Handler, PrivacyLogFilter], ...]
) -> None:
    for handler, privacy_filter in installed:
        handler.removeFilter(privacy_filter)
