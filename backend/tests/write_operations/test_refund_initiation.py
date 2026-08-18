"""Business and lifecycle tests for refund initiation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tools.context import ExecutionContext
from app.write_operations import (
    InitiateRefundInput,
    InitiateRefundOperation,
    RefundInitiationSnapshot,
    SQLAlchemyRefundInitiationReader,
    SQLAlchemyRefundInitiationStore,
    WriteExecutionContext,
    WriteFailurePhase,
    WriteFrameworkExecutor,
    WriteSecurityEnvelope,
    WriteStatus,
    WriteTransactionError,
)


NOW = datetime(2026, 7, 26, 14, 0, tzinfo=timezone.utc)
EXISTING_TIME = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)


class Reader:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get(self, order_number):
        return self.snapshot


class Store:
    def __init__(self, snapshot, *, raises=False):
        self.snapshot = snapshot
        self.raises = raises
        self.created = []

    def get_for_update(self, order_number):
        return self.snapshot

    def create_request(self, payment_id, currency, requested_at):
        if self.raises:
            raise RuntimeError("private payment persistence detail")
        self.created.append((payment_id, currency, requested_at))


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


def eligible(customer_id, **changes):
    values = {
        "order_number": "ORD-10025",
        "customer_id": customer_id,
        "order_status": "delivered",
        "order_payment_status": "paid",
        "payment_id": uuid4(),
        "payment_status": "succeeded",
        "payment_currency": "EGP",
        "eligibility_status": "eligible",
    }
    values.update(changes)
    return RefundInitiationSnapshot(**values)


def execute(initial, customer_id=None, *, locked=None, raises=False):
    trusted_customer = customer_id or (initial.customer_id if initial else uuid4())
    store = Store(locked or initial, raises=raises)
    transactions = Transactions(store)
    audit = Audit()
    operation = InitiateRefundOperation(
        Reader(initial), lambda transaction: transaction, clock=lambda: NOW
    )
    result = WriteFrameworkExecutor(transactions, audit).execute(
        operation,
        context(trusted_customer),
        InitiateRefundInput(order_number=" ord-10025 "),
    )
    return result, store, transactions, audit


def test_eligible_refund_request_is_created() -> None:
    initial = eligible(uuid4())
    result, store, transactions, audit = execute(initial)
    assert result.status is WriteStatus.SUCCESS
    assert result.outcome.refund_status == "pending"
    assert result.outcome.request_created is True
    assert result.outcome.requested_at == NOW
    assert store.created == [(initial.payment_id, "EGP", NOW)]
    assert (transactions.started, transactions.committed, transactions.rolled_back) == (1, 1, 0)
    event = audit.events[0]
    assert event.operation_name == "initiate_refund"
    assert event.business_change_applied is True
    assert event.operation_version == "1.0.0"
    assert event.resource_reference == "ORD-10025"
    assert "EGP" not in event.model_dump_json()


def test_existing_refund_is_idempotent_without_transaction() -> None:
    initial = eligible(
        uuid4(), existing_refund_status="pending",
        existing_refund_requested_at=EXISTING_TIME,
    )
    result, store, transactions, _ = execute(initial)
    assert result.error.error_code == "refund_already_requested"
    assert result.message == "A refund has already been requested for this order."
    assert transactions.started == 0
    assert store.created == []


def test_concurrent_duplicate_returns_no_change_and_creates_no_second_request() -> None:
    customer_id = uuid4()
    result, store, transactions, audit = execute(
        eligible(customer_id),
        locked=eligible(
            customer_id,
            existing_refund_status="pending",
            existing_refund_requested_at=EXISTING_TIME,
        ),
    )
    assert result.status is WriteStatus.SUCCESS
    assert result.outcome.request_created is False
    assert result.outcome.requested_at == EXISTING_TIME
    assert result.message == "A refund has already been requested for this order."
    assert store.created == []
    assert transactions.committed == 1
    assert audit.events[0].business_change_applied is False


@pytest.mark.parametrize(
    "changes",
    [
        {"order_status": "pending"},
        {"order_status": "cancelled"},
        {"order_payment_status": "pending"},
        {"payment_status": "pending"},
        {"payment_status": "failed"},
        {"payment_id": None},
        {"payment_currency": None},
        {"eligibility_status": "not_eligible"},
        {"eligibility_status": "undetermined"},
        {"eligibility_status": None},
    ],
)
def test_ineligible_orders_are_rejected_before_transaction(changes) -> None:
    result, store, transactions, _ = execute(eligible(uuid4(), **changes))
    assert result.error.error_code == "refund_not_allowed"
    assert result.error.phase is WriteFailurePhase.VALIDATION
    assert transactions.started == 0
    assert store.created == []


def test_missing_and_unowned_orders_are_indistinguishable() -> None:
    customer_id = uuid4()
    missing = execute(None, customer_id)[0]
    unowned = execute(eligible(uuid4()), customer_id)[0]
    for result in (missing, unowned):
        assert result.error.error_code == "order_not_found"
        assert result.message == "The requested order was not found."


def test_transaction_failure_rolls_back_without_financial_leakage() -> None:
    result, store, transactions, audit = execute(eligible(uuid4()), raises=True)
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert transactions.rolled_back == 1
    assert store.created == []
    serialized = result.model_dump_json() + audit.events[0].model_dump_json()
    assert "payment_id" not in serialized
    assert "EGP" not in serialized


def test_concurrent_eligibility_change_rolls_back() -> None:
    customer_id = uuid4()
    result, store, transactions, _ = execute(
        eligible(customer_id),
        locked=eligible(customer_id, eligibility_status="not_eligible"),
    )
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert transactions.rolled_back == 1
    assert store.created == []


def test_invalid_order_identifier_is_rejected() -> None:
    with pytest.raises(ValidationError):
        InitiateRefundInput(order_number=" ")
    with pytest.raises(ValidationError):
        InitiateRefundInput(order_number="x" * 65)


@pytest.mark.parametrize(
    ("reader", "store_factory", "clock"),
    [
        (object(), lambda transaction: transaction, lambda: NOW),
        (Reader(None), None, lambda: NOW),
        (Reader(None), lambda transaction: transaction, None),
    ],
)
def test_operation_rejects_invalid_dependencies(reader, store_factory, clock) -> None:
    with pytest.raises(TypeError):
        InitiateRefundOperation(reader, store_factory, clock)


def test_sqlalchemy_adapters_reject_invalid_usage() -> None:
    with pytest.raises(TypeError):
        SQLAlchemyRefundInitiationReader(object())
    with pytest.raises(RuntimeError):
        SQLAlchemyRefundInitiationStore(object()).create_request(uuid4(), "EGP", NOW)
