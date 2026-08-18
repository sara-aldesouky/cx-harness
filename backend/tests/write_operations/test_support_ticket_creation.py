"""Business and lifecycle tests for support-ticket creation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tools.context import ExecutionContext
from app.write_operations import (
    CreateSupportTicketInput,
    CreateSupportTicketOperation,
    SQLAlchemySupportTicketReader,
    SQLAlchemySupportTicketStore,
    SupportTicketSnapshot,
    WriteExecutionContext,
    WriteFailurePhase,
    WriteFrameworkExecutor,
    WriteSecurityEnvelope,
    WriteStatus,
    WriteTransactionError,
)


NOW = datetime(2026, 7, 26, 15, 0, tzinfo=timezone.utc)
EXISTING_TIME = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)


class Reader:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get(self, customer_id, order_number, issue_fingerprint):
        return self.snapshot


class Store:
    def __init__(self, snapshot, *, raises=False):
        self.snapshot = snapshot
        self.raises = raises
        self.created = []

    def get_for_update(self, customer_id, order_number, issue_fingerprint):
        return self.snapshot

    def create_ticket(self, **values):
        if self.raises:
            raise RuntimeError("private persistence detail")
        self.created.append(values)


class Transactions:
    def __init__(self, store):
        self.store = store
        self.started = self.committed = self.rolled_back = 0

    def execute(self, callback):
        self.started += 1
        try:
            result = callback(self.store)
        except Exception as error:
            self.rolled_back += 1
            raise WriteTransactionError(WriteTransactionError.public_message) from error
        self.committed += 1
        return result


class Audit:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


def context(customer_id):
    return WriteExecutionContext(
        execution_context=ExecutionContext(
            trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id,
            principal_role="customer",
        ),
        security=WriteSecurityEnvelope(
            authenticated=True, role_policy_allowed=True,
            tool_authorized=True, ownership_authorized=True,
        ),
        request_id=uuid4(), correlation_id=uuid4(), requested_at=NOW,
    )


def available(**changes):
    values = {"customer_exists": True, "order_owned": True}
    values.update(changes)
    return SupportTicketSnapshot(**values)


def ticket_input(**changes):
    values = {
        "category": "general_inquiry",
        "issue_description": "I still need help resolving this customer issue.",
        "escalation_reason": "customer_requested",
    }
    values.update(changes)
    return CreateSupportTicketInput(**values)


def execute(input_model, initial=None, *, locked=None, raises=False):
    initial = initial or available()
    store = Store(locked or initial, raises=raises)
    transactions = Transactions(store)
    audit = Audit()
    operation = CreateSupportTicketOperation(
        Reader(initial), lambda transaction: transaction,
        clock=lambda: NOW, reference_factory=lambda: "TKT-ABC123DEF456",
    )
    result = WriteFrameworkExecutor(transactions, audit).execute(
        operation, context(uuid4()), input_model
    )
    return result, store, transactions, audit


def test_general_customer_requested_ticket_is_created() -> None:
    result, store, transactions, audit = execute(ticket_input())
    assert result.status is WriteStatus.SUCCESS
    assert result.outcome.ticket_reference == "TKT-ABC123DEF456"
    assert result.outcome.priority == "low"
    assert result.outcome.status == "open"
    assert result.outcome.ticket_created is True
    assert store.created[0]["issue_description"].startswith("I still need help")
    assert (transactions.started, transactions.committed, transactions.rolled_back) == (1, 1, 0)
    event = audit.events[0]
    assert event.business_change_applied is True
    assert event.resource_reference == "ticket:TKT-ABC123DEF456"
    assert "customer issue" not in event.model_dump_json()


def test_related_order_ticket_records_only_safe_order_reference_in_audit() -> None:
    order_id = uuid4()
    result, store, _, audit = execute(
        ticket_input(category="order_issue", order_number=" ord-10025 "),
        available(related_order_id=order_id),
    )
    assert result.outcome.related_order_number == "ORD-10025"
    assert result.outcome.priority == "medium"
    assert store.created[0]["related_order_id"] == order_id
    assert audit.events[0].resource_reference == (
        "ticket:TKT-ABC123DEF456|order:ORD-10025"
    )


@pytest.mark.parametrize(
    ("category", "reason", "expected"),
    [
        ("general_inquiry", "customer_requested", "low"),
        ("delivery_issue", "unresolved_issue", "medium"),
        ("technical_issue", "automation_failed", "medium"),
        ("payment_issue", "unresolved_issue", "high"),
        ("refund_issue", "customer_requested", "high"),
        ("general_inquiry", "operation_blocked", "high"),
    ],
)
def test_priority_assignment_is_centralized(category, reason, expected) -> None:
    result = execute(ticket_input(category=category, escalation_reason=reason))[0]
    assert result.outcome.priority == expected


def test_duplicate_is_idempotent_without_transaction() -> None:
    existing = available(
        existing_ticket_reference="TKT-EXISTING123",
        existing_ticket_priority="medium",
        existing_ticket_status="open",
        existing_ticket_created_at=EXISTING_TIME,
    )
    result, store, transactions, _ = execute(ticket_input(), existing)
    assert result.error.error_code == "support_ticket_already_exists"
    assert result.message == "An active support ticket already exists for this issue."
    assert transactions.started == 0
    assert store.created == []


def test_concurrent_duplicate_returns_existing_logical_outcome() -> None:
    existing = available(
        existing_ticket_reference="TKT-EXISTING123",
        existing_ticket_priority="high",
        existing_ticket_status="open",
        existing_ticket_created_at=EXISTING_TIME,
    )
    result, store, transactions, audit = execute(
        ticket_input(category="payment_issue"), available(), locked=existing
    )
    assert result.status is WriteStatus.SUCCESS
    assert result.outcome.ticket_created is False
    assert result.outcome.ticket_reference == "TKT-EXISTING123"
    assert result.message == "An active support ticket already exists for this issue."
    assert store.created == []
    assert transactions.committed == 1
    assert "TKT-EXISTING123" in audit.events[0].resource_reference
    assert audit.events[0].business_change_applied is False


def test_missing_customer_and_unowned_order_fail_before_transaction() -> None:
    missing_customer = execute(ticket_input(), available(customer_exists=False))[0]
    unowned_result, _, unowned_transactions, _ = execute(
        ticket_input(order_number="ORD-OTHER"), available(order_owned=False)
    )
    assert missing_customer.error.error_code == "customer_not_found"
    assert unowned_result.error.error_code == "order_not_found"
    assert unowned_transactions.started == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "unknown"},
        {"issue_description": ""},
        {"issue_description": "short"},
        {"issue_description": "x" * 2001},
        {"escalation_reason": "invented"},
        {"order_number": " "},
    ],
)
def test_invalid_ticket_inputs_are_rejected(changes) -> None:
    with pytest.raises(ValidationError):
        ticket_input(**changes)


def test_issue_fingerprint_is_deterministic_after_normalization() -> None:
    first = ticket_input(issue_description="Repeated   customer issue details")
    second = ticket_input(issue_description=" repeated customer ISSUE details ")
    assert first.issue_fingerprint == second.issue_fingerprint


def test_transaction_failure_rolls_back_and_does_not_leak_issue() -> None:
    input_model = ticket_input()
    result, store, transactions, audit = execute(input_model, raises=True)
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert transactions.rolled_back == 1
    assert store.created == []
    serialized = result.model_dump_json() + audit.events[0].model_dump_json()
    assert input_model.issue_description not in serialized


def test_concurrent_ownership_change_rolls_back() -> None:
    result, store, transactions, _ = execute(
        ticket_input(order_number="ORD-10025"), available(),
        locked=available(order_owned=False),
    )
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert transactions.rolled_back == 1
    assert store.created == []


@pytest.mark.parametrize(
    ("reader", "store_factory", "clock", "reference_factory"),
    [
        (object(), lambda transaction: transaction, lambda: NOW, lambda: "TKT-X"),
        (Reader(available()), None, lambda: NOW, lambda: "TKT-X"),
        (Reader(available()), lambda transaction: transaction, None, lambda: "TKT-X"),
        (Reader(available()), lambda transaction: transaction, lambda: NOW, None),
    ],
)
def test_operation_rejects_invalid_dependencies(
    reader, store_factory, clock, reference_factory
) -> None:
    with pytest.raises(TypeError):
        CreateSupportTicketOperation(reader, store_factory, clock, reference_factory)


def test_sqlalchemy_adapters_reject_invalid_usage() -> None:
    with pytest.raises(TypeError):
        SQLAlchemySupportTicketReader(object())
    with pytest.raises(RuntimeError):
        SQLAlchemySupportTicketStore(object()).create_ticket(
            ticket_reference="TKT-1", customer_id=uuid4(), related_order_id=None,
            category="general_inquiry", priority="low", issue_description="safe issue",
            issue_fingerprint="a" * 64, created_at=NOW,
        )
