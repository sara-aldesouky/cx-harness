"""Business and lifecycle tests for delivery-address updates."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tools.context import ExecutionContext
from app.write_operations import (
    AddressUpdateSnapshot,
    SQLAlchemyAddressUpdateReader,
    SQLAlchemyAddressUpdateStore,
    UpdateDeliveryAddressInput,
    UpdateDeliveryAddressOperation,
    WriteExecutionContext,
    WriteFailurePhase,
    WriteFrameworkExecutor,
    WriteSecurityEnvelope,
    WriteStatus,
    WriteTransactionError,
)


NOW = datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc)
OLD_TIME = datetime(2026, 7, 25, 13, 0, tzinfo=timezone.utc)
OLD_ADDRESS = "10 Market Street, Cairo"
NEW_ADDRESS = "22 Nile Road, Giza"


class Reader:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get(self, order_number):
        return self.snapshot


class Store:
    def __init__(self, snapshot, *, raises=False):
        self.snapshot = snapshot
        self.raises = raises
        self.updates = []

    def get_for_update(self, order_number):
        return self.snapshot

    def update_address(self, order_number, delivery_address, updated_at):
        if self.raises:
            raise RuntimeError("private persistence detail")
        self.updates.append((order_number, delivery_address, updated_at))


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


def snapshot(customer_id, status="pending", address=OLD_ADDRESS):
    return AddressUpdateSnapshot(
        order_number="ORD-10025", customer_id=customer_id, status=status,
        delivery_address=address, updated_at=OLD_TIME,
    )


def execute(initial, customer_id=None, *, locked=None, raises=False):
    trusted_customer = customer_id or (initial.customer_id if initial else uuid4())
    store = Store(locked or initial, raises=raises)
    transactions = Transactions(store)
    audit = Audit()
    operation = UpdateDeliveryAddressOperation(
        Reader(initial), lambda transaction: transaction, clock=lambda: NOW
    )
    result = WriteFrameworkExecutor(transactions, audit).execute(
        operation,
        context(trusted_customer),
        UpdateDeliveryAddressInput(
            order_number=" ord-10025 ", delivery_address="  22 Nile Road,   Giza  "
        ),
    )
    return result, store, transactions, audit


@pytest.mark.parametrize("status", ["pending", "confirmed", "preparing"])
def test_eligible_orders_update_address(status) -> None:
    result, store, transactions, audit = execute(snapshot(uuid4(), status))
    assert result.status is WriteStatus.SUCCESS
    assert result.outcome.address_updated is True
    assert result.outcome.order_number == "ORD-10025"
    assert result.message == "The delivery address was updated successfully."
    assert store.updates == [("ORD-10025", NEW_ADDRESS, NOW)]
    assert (transactions.started, transactions.committed, transactions.rolled_back) == (1, 1, 0)
    event = audit.events[0]
    assert event.operation_name == "update_delivery_address"
    assert event.business_change_applied is True
    assert event.resource_reference == "ORD-10025"
    assert NEW_ADDRESS not in event.model_dump_json()


@pytest.mark.parametrize("status", ["dispatched", "delayed", "delivered", "cancelled"])
def test_ineligible_statuses_are_rejected_before_transaction(status) -> None:
    result, store, transactions, _ = execute(snapshot(uuid4(), status))
    assert result.error.error_code == "delivery_address_update_not_allowed"
    assert result.error.phase is WriteFailurePhase.VALIDATION
    assert transactions.started == 0
    assert store.updates == []


def test_unchanged_address_is_idempotent_without_transaction() -> None:
    customer_id = uuid4()
    result, store, transactions, audit = execute(
        snapshot(customer_id, address=NEW_ADDRESS), customer_id
    )
    assert result.error.error_code == "address_already_up_to_date"
    assert result.message == "The delivery address is already up to date."
    assert transactions.started == 0
    assert store.updates == []


def test_concurrent_identical_update_performs_no_second_write() -> None:
    customer_id = uuid4()
    result, store, transactions, audit = execute(
        snapshot(customer_id, address=OLD_ADDRESS),
        locked=snapshot(customer_id, address=NEW_ADDRESS),
    )
    assert result.status is WriteStatus.SUCCESS
    assert result.outcome.address_updated is False
    assert result.message == "The delivery address is already up to date."
    assert store.updates == []
    assert transactions.committed == 1
    assert audit.events[0].business_change_applied is False


def test_concurrent_ineligible_state_rolls_back_without_overwrite() -> None:
    customer_id = uuid4()
    result, store, transactions, _ = execute(
        snapshot(customer_id, status="preparing"),
        locked=snapshot(customer_id, status="dispatched"),
    )
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert transactions.rolled_back == 1
    assert store.updates == []


def test_missing_and_unowned_orders_are_indistinguishable() -> None:
    customer_id = uuid4()
    missing = execute(None, customer_id)[0]
    unowned = execute(snapshot(uuid4()), customer_id)[0]
    for result in (missing, unowned):
        assert result.error.error_code == "order_not_found"
        assert result.message == "The requested order was not found."


def test_transaction_failure_rolls_back_without_leaking_address() -> None:
    result, _, transactions, audit = execute(snapshot(uuid4()), raises=True)
    assert result.error.phase is WriteFailurePhase.TRANSACTION
    assert transactions.rolled_back == 1
    assert NEW_ADDRESS not in result.model_dump_json()
    assert NEW_ADDRESS not in audit.events[0].model_dump_json()


@pytest.mark.parametrize(
    "address",
    ["", "   ", "x" * 501, "12 Safe Street 🚚", "---"],
)
def test_invalid_addresses_are_rejected(address) -> None:
    with pytest.raises(ValidationError):
        UpdateDeliveryAddressInput(order_number="ORD-1", delivery_address=address)


def test_address_normalization_supports_customer_safe_unicode() -> None:
    model = UpdateDeliveryAddressInput(
        order_number="ord-1", delivery_address="  ١٢ شارع النيل، القاهرة  ".replace("،", ",")
    )
    assert model.order_number == "ORD-1"
    assert model.delivery_address == "١٢ شارع النيل, القاهرة"


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
        UpdateDeliveryAddressOperation(reader, store_factory, clock)


def test_sqlalchemy_adapters_reject_invalid_usage() -> None:
    with pytest.raises(TypeError):
        SQLAlchemyAddressUpdateReader(object())
    with pytest.raises(RuntimeError):
        SQLAlchemyAddressUpdateStore(object()).update_address("ORD-1", NEW_ADDRESS, NOW)
