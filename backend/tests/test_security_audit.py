"""Pure tests for resilient, PII-free security audit events."""

import json
from uuid import uuid4

from app.security_audit import (
    AuditCategory,
    AuditResult,
    AuditSeverity,
    SecurityAuditRecorder,
    SecurityEventType,
)


class RecordingSink:
    def __init__(self, error=None) -> None:
        self.events = []
        self.error = error

    def emit(self, event) -> None:
        if self.error:
            raise self.error
        self.events.append(event)


def recorder(sink=None, fallback=None) -> SecurityAuditRecorder:
    return SecurityAuditRecorder(
        "security-audit-test-key-with-at-least-32-characters",
        sink=sink or RecordingSink(),
        fallback_sink=fallback or RecordingSink(),
    )


def test_stable_pseudonyms_are_keyed_and_never_raw() -> None:
    subject = uuid4()
    first = recorder()
    second = recorder()
    other_key = SecurityAuditRecorder("z" * 32)

    assert first.pseudonymize(subject) == first.pseudonymize(subject)
    assert first.pseudonymize(subject) == second.pseudonymize(subject)
    assert first.pseudonymize(subject) != other_key.pseudonymize(subject)
    assert str(subject) not in first.pseudonymize(subject)


def test_structured_event_contains_no_raw_pii_or_secrets() -> None:
    sink = RecordingSink()
    audit = recorder(sink)
    customer_id = uuid4()
    conversation_id = uuid4()
    audit.record(
        SecurityEventType.OWNERSHIP_DENIED,
        severity=AuditSeverity.WARNING,
        result=AuditResult.FAILURE,
        category=AuditCategory.AUTHORIZATION,
        role="customer",
        tool_name="get_order_status",
        capabilities=("order",),
        correlation_id=conversation_id,
        customer_id=customer_id,
        session_id=conversation_id,
        failure_reason_code="unauthorized_resource",
    )

    payload = json.dumps(sink.events[0].model_dump(mode="json"))
    assert str(customer_id) not in payload
    assert str(conversation_id) not in payload
    assert "@" not in payload
    assert sink.events[0].customer_pseudonym.startswith("psn_")
    assert sink.events[0].severity is AuditSeverity.WARNING


def test_unsafe_labels_are_not_written_to_audit_records() -> None:
    sink = RecordingSink()
    audit = recorder(sink)
    audit.record(
        SecurityEventType.UNKNOWN_TOOL_ATTEMPT,
        severity=AuditSeverity.WARNING,
        result=AuditResult.FAILURE,
        category=AuditCategory.SECURITY,
        tool_name="john@example.com",
        failure_reason_code="token=secret-value",
    )
    event = sink.events[0]
    assert event.tool_name == "redacted"
    assert event.failure_reason_code == "redacted"


def test_sink_failure_never_raises_and_emits_fallback_failure_event() -> None:
    fallback = RecordingSink()
    audit = recorder(RecordingSink(RuntimeError("sink unavailable")), fallback)

    audit.record(
        SecurityEventType.AUTHENTICATION_SUCCEEDED,
        severity=AuditSeverity.INFO,
        result=AuditResult.SUCCESS,
        category=AuditCategory.AUTHENTICATION,
        customer_id=uuid4(),
    )

    assert len(fallback.events) == 1
    assert fallback.events[0].event_type is SecurityEventType.AUDIT_SUBSYSTEM_FAILED
    assert fallback.events[0].severity is AuditSeverity.CRITICAL


def test_repeated_failures_generate_one_suspicious_event_at_threshold() -> None:
    sink = RecordingSink()
    audit = recorder(sink)
    customer_id = uuid4()
    for _ in range(3):
        audit.record(
            SecurityEventType.TOOL_AUTHORIZATION_DENIED,
            severity=AuditSeverity.WARNING,
            result=AuditResult.FAILURE,
            category=AuditCategory.AUTHORIZATION,
            customer_id=customer_id,
            failure_reason_code="tool_not_permitted",
        )

    assert [event.event_type for event in sink.events].count(
        SecurityEventType.SUSPICIOUS_REPEATED_FAILURES
    ) == 1


def test_configuration_problem_is_a_safe_system_event() -> None:
    sink = RecordingSink()
    audit = recorder(sink)
    audit.configuration_problem()
    event = sink.events[0]
    assert event.event_type is SecurityEventType.SECURITY_CONFIGURATION_PROBLEM
    assert event.category is AuditCategory.SYSTEM
    assert event.severity is AuditSeverity.ERROR
