"""Business and lifecycle tests for the first concrete write operation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.tools.context import ExecutionContext
from app.write_operations import (
    CancelOrderInput,
    CancelOrderOperation,
    OrderCancellationSnapshot,
    SQLAlchemyOrderCancellationReader,
    SQLAlchemyOrderCancellationStore,
    SQLAlchemyTransactionManager,
    WriteExecutionContext,
    WriteFailurePhase,
    WriteFrameworkExecutor,
    WriteSecurityEnvelope,
    WriteStatus,
    WriteTransactionError,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


class Reader:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0

    def get(self, order_number):
        self.calls += 1
        return self.snapshot


class Store:
    def __init__(self, snapshot, *, raises=False):
        self.snapshot = snapshot
        self.raises = raises
        self.marked = []

    def get_for_update(self, order_number):
        return self.snapshot

    def mark_cancelled(self, order_number, cancelled_at):
        if self.raises:
            raise RuntimeError("private database failure")
        self.marked.append((order_number, cancelled_at))
        self.snapshot = self.snapshot.model_copy(update={"status": "cancelled"})


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


def write_context(customer_id):
    return WriteExecutionContext(
        execution_context=ExecutionContext(
            trace_id=uuid4(),
            execution_id=uuid4(),
            conversation_id=uuid4(),
            customer_id=customer_id,
            principal_role="customer",
        ),
        security=WriteSecurityEnvelope(
            authenticated=True,
            role_policy_allowed=True,
            tool_authorized=True,
            ownership_authorized=True,
        ),
        request_id=uuid4(),
        correlation_id=uuid4(),
        requested_at=NOW,
    )


def snapshot(customer_id, status):
    return OrderCancellationSnapshot(
        order_number="ORD-10025", customer_id=customer_id, status=status
    )


def execute(initial, context_customer=None, *, transaction_snapshot=None, raises=False):
    customer_id = context_customer or (initial.customer_id if initial else uuid4())
    reader = Reader(initial)
    store = Store(transaction_snapshot or initial, raises=raises)
    transactions = Transactions(store)
    audit = Audit()
    operation = CancelOrderOperation(reader, lambda transaction: transaction, clock=lambda: NOW)
    result = WriteFrameworkExecutor(transactions, audit).execute(
        operation, write_context(customer_id), CancelOrderInput(order_number=" ord-10025 ")
    )
    return result, reader, store, transactions, audit


@pytest.mark.parametrize("status", ["pending", "confirmed", "preparing"])
def test_eligible_statuses_cancel_successfully(status) -> None:
    customer_id = uuid4()
    result, reader, store, transactions, audit = execute(snapshot(customer_id, status))

    assert result.status is WriteStatus.SUCCESS
    assert result.outcome.order_number == "ORD-10025"
    assert result.outcome.status == "cancelled"
    assert result.outcome.cancelled_at == NOW
    assert store.marked == [("ORD-10025", NOW)]
    assert (transactions.started, transactions.committed, transactions.rolled_back) == (1, 1, 0)
    assert reader.calls == 1
    assert audit.events[0].operation_name == "cancel_order"
    assert audit.events[0].business_change_applied is True
    assert audit.events[0].resource_reference == "ORD-10025"
    assert audit.events[0].timestamp.tzinfo is not None


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        ("dispatched", "order_cancellation_not_allowed", "This order can no longer be cancelled."),
        ("delivered", "order_cancellation_not_allowed", "This order can no longer be cancelled."),
        ("cancelled", "order_already_cancelled", "This order has already been cancelled."),
    ],
)
def test_ineligible_and_repeated_cancellation_is_deterministic(status, code, message) -> None:
    result, _, store, transactions, audit = execute(snapshot(uuid4(), status))
    assert result.status is WriteStatus.FAILURE
    assert result.error.error_code == code
    assert result.error.phase is WriteFailurePhase.VALIDATION
    assert result.message == message
    assert transactions.started == 0
    assert store.marked == []
    assert audit.events[0].failure_code == code
    assert audit.events[0].business_change_applied is None


def test_missing_and_unowned_orders_use_same_safe_failure() -> None:
    customer_id = uuid4()
    missing = execute(None, customer_id)[0]
    unowned = execute(snapshot(uuid4(), "pending"), customer_id)[0]
    for result in (missing, unowned):
        assert result.error.error_code == "order_not_found"
        assert result.message == "The requested order was not found."


def test_transaction_failure_rolls_back_and_is_safe() -> None:
    result, _, store, transactions, _ = execute(snapshot(uuid4(), "pending"), raises=True)
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert transactions.rolled_back == 1
    assert transactions.committed == 0
    assert store.marked == []
    assert "database" not in result.model_dump_json().lower()


def test_concurrent_state_change_is_locked_rechecked_and_rolled_back() -> None:
    customer_id = uuid4()
    result, _, store, transactions, _ = execute(
        snapshot(customer_id, "pending"),
        transaction_snapshot=snapshot(customer_id, "dispatched"),
    )
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert transactions.rolled_back == 1
    assert store.marked == []


def test_input_validation_rejects_invalid_order_identifiers() -> None:
    with pytest.raises(ValueError):
        CancelOrderInput(order_number=" ")
    with pytest.raises(ValueError):
        CancelOrderInput(order_number="x" * 65)


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
        CancelOrderOperation(reader, store_factory, clock)


def test_naive_cancellation_clock_rolls_back() -> None:
    customer_id = uuid4()
    initial = snapshot(customer_id, "pending")
    store = Store(initial)
    operation = CancelOrderOperation(
        Reader(initial), lambda transaction: transaction, clock=datetime.now
    )
    result = WriteFrameworkExecutor(Transactions(store)).execute(
        operation,
        write_context(customer_id),
        CancelOrderInput(order_number="ORD-10025"),
    )
    assert result.error.phase is WriteFailurePhase.TRANSACTION


def test_sqlalchemy_adapters_reject_invalid_usage() -> None:
    with pytest.raises(TypeError):
        SQLAlchemyOrderCancellationReader(object())
    with pytest.raises(RuntimeError):
        SQLAlchemyOrderCancellationStore(object()).mark_cancelled("ORD-1", NOW)


def test_transaction_adapter_rejects_non_callable_callback() -> None:
    class Factory:
        def begin(self):
            raise AssertionError("must not begin")

    with pytest.raises(TypeError):
        SQLAlchemyTransactionManager(Factory()).execute(None)
