"""Resilient provider-independent security audit events and sinks."""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import re
from collections import OrderedDict
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from threading import Lock
from typing import Callable, Mapping, Optional, Protocol, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.identity_roles import PrincipalRole


logger = logging.getLogger("app.security_audit")


class AuditSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AuditResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class AuditCategory(str, Enum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    PRIVACY = "privacy"
    SECURITY = "security"
    SYSTEM = "system"


class SecurityEventType(str, Enum):
    AUTHENTICATION_SUCCEEDED = "authentication_succeeded"
    AUTHENTICATION_FAILED = "authentication_failed"
    CREDENTIALS_EXPIRED = "credentials_expired"
    INVALID_CREDENTIALS = "invalid_credentials"
    OWNERSHIP_DENIED = "ownership_denied"
    ROLE_POLICY_DENIED = "role_policy_denied"
    TOOL_AUTHORIZATION_DENIED = "tool_authorization_denied"
    UNKNOWN_TOOL_ATTEMPT = "unknown_tool_attempt"
    DATA_REDACTION_PERFORMED = "data_redaction_performed"
    PROMPT_SANITIZED = "prompt_sanitized"
    UNSAFE_OUTPUT_BLOCKED = "unsafe_output_blocked"
    SUSPICIOUS_REPEATED_FAILURES = "suspicious_repeated_failures"
    INVALID_ROLE_ESCALATION = "invalid_role_escalation"
    INVALID_CUSTOMER_IMPERSONATION = "invalid_customer_impersonation"
    POLICY_EVALUATION_FAILED = "policy_evaluation_failed"
    AUTHORIZATION_UNAVAILABLE = "authorization_unavailable"
    AUDIT_SUBSYSTEM_FAILED = "audit_subsystem_failed"
    SECURITY_CONFIGURATION_PROBLEM = "security_configuration_problem"
    TOKEN_REPLAY_DETECTED = "token_replay_detected"
    REVOKED_TOKEN_USED = "revoked_token_used"
    REPLAY_PROTECTION_UNAVAILABLE = "replay_protection_unavailable"


class SecurityAuditEvent(BaseModel):
    """Immutable, PII-free security event ready for a log or SIEM sink."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    event_type: SecurityEventType
    severity: AuditSeverity
    result: AuditResult
    category: AuditCategory
    trusted_role: Optional[PrincipalRole] = None
    tool_name: Optional[str] = None
    tool_version: Optional[str] = None
    capabilities: tuple[str, ...] = ()
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    customer_pseudonym: Optional[str] = None
    session_pseudonym: Optional[str] = None
    failure_reason_code: Optional[str] = None

    @field_validator(
        "correlation_id",
        "request_id",
        "customer_pseudonym",
        "session_pseudonym",
    )
    @classmethod
    def require_pseudonym(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.startswith("psn_"):
            raise ValueError("audit identifiers must be pseudonymous")
        return value


class SecurityAuditSink(Protocol):
    def emit(self, event: SecurityAuditEvent) -> None: ...


class LoggingSecurityAuditSink:
    """Emit one JSON event without exception objects or customer payloads."""

    def emit(self, event: SecurityAuditEvent) -> None:
        logger.log(
            getattr(logging, event.severity.value),
            "security_audit %s",
            json.dumps(event.model_dump(mode="json"), sort_keys=True),
        )


class AuditQueue(Protocol):
    """Minimal queue behavior supported by local and cloud queue clients."""

    def put_nowait(self, item: Mapping[str, object]) -> None: ...


class QueueSecurityAuditSink:
    """Publish JSON-safe events to an injected non-blocking queue."""

    def __init__(self, queue: AuditQueue) -> None:
        if not callable(getattr(queue, "put_nowait", None)):
            raise TypeError("queue must provide put_nowait()")
        self._queue = queue

    def emit(self, event: SecurityAuditEvent) -> None:
        self._queue.put_nowait(event.model_dump(mode="json"))


class SIEMSecurityAuditSink:
    """Send JSON-safe events through a vendor-neutral injected transport.

    The transport callable can be implemented by Splunk, Sentinel, Chronicle,
    an HTTP collector, or a managed cloud logging adapter without changing the
    recorder or security event contract.
    """

    def __init__(self, sender: Callable[[Mapping[str, object]], None]) -> None:
        if not callable(sender):
            raise TypeError("sender must be callable")
        self._sender = sender

    def emit(self, event: SecurityAuditEvent) -> None:
        self._sender(event.model_dump(mode="json"))


class SecurityAuditRecorder:
    """Pseudonymize and publish events without affecting business execution."""

    _FAILURE_THRESHOLD = 3
    _MAX_TRACKED_SUBJECTS = 10_000
    _SAFE_LABEL = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")

    def __init__(
        self,
        pseudonym_key: Union[str, bytes],
        sink: Optional[SecurityAuditSink] = None,
        fallback_sink: Optional[SecurityAuditSink] = None,
    ) -> None:
        self._key = self._normalize_key(pseudonym_key)
        self._sink = sink or LoggingSecurityAuditSink()
        self._fallback = fallback_sink or LoggingSecurityAuditSink()
        self._failures: OrderedDict[str, int] = OrderedDict()
        self._lock = Lock()

    def configure_key(self, pseudonym_key: Union[str, bytes]) -> None:
        """Replace the process bootstrap key from trusted startup settings."""

        self._key = self._normalize_key(pseudonym_key)

    def pseudonymize(self, value: object) -> Optional[str]:
        if value is None:
            return None
        digest = hmac.new(
            self._key, str(value).strip().encode("utf-8"), sha256
        ).hexdigest()
        return f"psn_{digest[:24]}"

    def record(
        self,
        event_type: SecurityEventType,
        *,
        severity: AuditSeverity,
        result: AuditResult,
        category: AuditCategory,
        role: Optional[Union[PrincipalRole, str]] = None,
        tool_name: Optional[str] = None,
        tool_version: Optional[str] = None,
        capabilities: tuple[str, ...] = (),
        correlation_id: Optional[object] = None,
        request_id: Optional[object] = None,
        customer_id: Optional[object] = None,
        session_id: Optional[object] = None,
        failure_reason_code: Optional[str] = None,
    ) -> None:
        """Best-effort emission; this method never raises to business code."""

        try:
            try:
                trusted_role = PrincipalRole(role) if role is not None else None
            except (TypeError, ValueError):
                trusted_role = None
            event = SecurityAuditEvent(
                timestamp=datetime.now(timezone.utc),
                event_type=event_type,
                severity=severity,
                result=result,
                category=category,
                trusted_role=trusted_role,
                tool_name=self._safe_label(tool_name),
                tool_version=self._safe_label(tool_version),
                capabilities=tuple(
                    sorted(
                        label
                        for item in set(capabilities)
                        if (label := self._safe_label(item)) is not None
                    )
                ),
                correlation_id=self.pseudonymize(correlation_id),
                request_id=self.pseudonymize(request_id),
                customer_pseudonym=self.pseudonymize(customer_id),
                session_pseudonym=self.pseudonymize(session_id),
                failure_reason_code=self._safe_label(failure_reason_code),
            )
            self._sink.emit(event)
            if result is AuditResult.FAILURE and event.customer_pseudonym:
                self._track_failure(event.customer_pseudonym, event)
        except Exception:
            self._emit_audit_failure()

    def configuration_problem(self) -> None:
        self.record(
            SecurityEventType.SECURITY_CONFIGURATION_PROBLEM,
            severity=AuditSeverity.ERROR,
            result=AuditResult.FAILURE,
            category=AuditCategory.SYSTEM,
            failure_reason_code="audit_pseudonym_key_missing",
        )

    def _track_failure(
        self, customer_pseudonym: str, source: SecurityAuditEvent
    ) -> None:
        with self._lock:
            count = self._failures.pop(customer_pseudonym, 0) + 1
            self._failures[customer_pseudonym] = count
            while len(self._failures) > self._MAX_TRACKED_SUBJECTS:
                self._failures.popitem(last=False)
        if count == self._FAILURE_THRESHOLD:
            repeated = SecurityAuditEvent(
                timestamp=datetime.now(timezone.utc),
                event_type=SecurityEventType.SUSPICIOUS_REPEATED_FAILURES,
                severity=AuditSeverity.WARNING,
                result=AuditResult.FAILURE,
                category=AuditCategory.SECURITY,
                trusted_role=source.trusted_role,
                tool_name=source.tool_name,
                tool_version=source.tool_version,
                capabilities=source.capabilities,
                correlation_id=source.correlation_id,
                request_id=source.request_id,
                customer_pseudonym=customer_pseudonym,
                session_pseudonym=source.session_pseudonym,
                failure_reason_code="repeated_security_failures",
            )
            try:
                self._sink.emit(repeated)
            except Exception:
                self._emit_audit_failure()

    def _emit_audit_failure(self) -> None:
        try:
            self._fallback.emit(
                SecurityAuditEvent(
                    timestamp=datetime.now(timezone.utc),
                    event_type=SecurityEventType.AUDIT_SUBSYSTEM_FAILED,
                    severity=AuditSeverity.CRITICAL,
                    result=AuditResult.FAILURE,
                    category=AuditCategory.SYSTEM,
                    failure_reason_code="audit_sink_failure",
                )
            )
        except Exception:
            pass

    @classmethod
    def _safe_label(cls, value: Optional[object]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized if cls._SAFE_LABEL.fullmatch(normalized) else "redacted"

    @staticmethod
    def _normalize_key(value: Union[str, bytes]) -> bytes:
        encoded = value.encode("utf-8") if isinstance(value, str) else value
        if not isinstance(encoded, bytes) or len(encoded) < 32:
            raise ValueError("audit pseudonym key must contain at least 32 bytes")
        return encoded


security_audit_recorder = SecurityAuditRecorder(secrets.token_bytes(32))
