"""Unit tests for read-only Orders domain capabilities."""

from datetime import datetime, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import app.tools.order_capabilities as capabilities
from app.tools import (
    ExecutionContext,
    GetOrderDetailsTool,
    GetOrderItemsTool,
    ListCurrentOrdersTool,
    ListOrderHistoryTool,
    OrderItemsInput,
    OrderNumberInput,
    PaginationInput,
    ToolCategory,
    ToolStatus,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeSession:
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return None


class FakeCustomerRepository:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists

    def get_by_id(self, customer_id):  # type: ignore[no-untyped-def]
        return object() if self.exists else None


class FakeOrderRepository:
    def __init__(self, stored_order, listed_orders):  # type: ignore[no-untyped-def]
        self.stored_order = stored_order
        self.listed_orders = listed_orders
        self.calls = []

    def get_by_order_number(self, value):  # type: ignore[no-untyped-def]
        self.calls.append(("get", value))
        return self.stored_order

    def list_current_by_customer_id(self, customer_id, limit, offset):  # type: ignore[no-untyped-def]
        self.calls.append(("current", customer_id, limit, offset))
        return self.listed_orders

    def count_current_by_customer_id(self, customer_id):  # type: ignore[no-untyped-def]
        return len(self.listed_orders)

    def list_history_by_customer_id(self, customer_id, limit, offset):  # type: ignore[no-untyped-def]
        self.calls.append(("history", customer_id, limit, offset))
        return self.listed_orders

    def count_history_by_customer_id(self, customer_id):  # type: ignore[no-untyped-def]
        return len(self.listed_orders)


class FakeItemRepository:
    def __init__(self, items):  # type: ignore[no-untyped-def]
        self.items = items
        self.calls = []

    def list_by_order_id(self, order_id, limit, offset):  # type: ignore[no-untyped-def]
        self.calls.append((order_id, limit, offset))
        return self.items

    def count(self, *, order_id):  # type: ignore[no-untyped-def]
        return len(self.items)


def trusted_context(customer_id=None):  # type: ignore[no-untyped-def]
    return ExecutionContext(
        trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id
    )


def order(customer_id, *, status="preparing"):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        id=uuid4(),
        customer_id=customer_id,
        order_number="ORD-10025",
        status=status,
        payment_status="paid",
        total_amount=Decimal("50.00"),
        estimated_delivery_time=NOW,
        created_at=NOW,
        updated_at=NOW,
        delivery_address="sensitive address",
    )


def item():  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        product_name="Milk",
        quantity=2,
        unit_price=Decimal("3.50"),
        item_status="included",
    )


def configure(monkeypatch, stored_order, listed_orders=(), items=(), *, customer_exists=True):  # type: ignore[no-untyped-def]
    session = FakeSession()
    orders = FakeOrderRepository(stored_order, list(listed_orders))
    item_repository = FakeItemRepository(list(items))
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: lambda: session
    )
    monkeypatch.setattr(
        capabilities,
        "CustomerRepository",
        lambda received: FakeCustomerRepository(customer_exists),
    )
    monkeypatch.setattr(capabilities, "OrderRepository", lambda received: orders)
    monkeypatch.setattr(
        capabilities, "OrderItemRepository", lambda received: item_repository
    )
    return orders, item_repository


def test_input_validation_normalization_and_extra_rejection() -> None:
    assert OrderNumberInput(order_number=" ord-10025 ").order_number == "ORD-10025"
    with pytest.raises(ValidationError):
        OrderNumberInput(order_number="invalid")
    with pytest.raises(ValidationError):
        PaginationInput(limit=0)
    with pytest.raises(ValidationError):
        PaginationInput(offset=-1)
    with pytest.raises(ValidationError):
        OrderItemsInput(order_number="ORD-10025", customer_id=str(uuid4()))


def test_order_capability_metadata_is_read_only_and_ownership_bound() -> None:
    for tool in (
        ListCurrentOrdersTool,
        ListOrderHistoryTool,
        GetOrderDetailsTool,
        GetOrderItemsTool,
    ):
        assert tool.metadata.category is ToolCategory.ORDER
        assert tool.metadata.is_read_only
        assert tool.metadata.requires_customer_identity
        assert tool.metadata.requires_order_ownership


@pytest.mark.parametrize(
    ("tool", "expected_call"),
    [
        (ListCurrentOrdersTool(), "current"),
        (ListOrderHistoryTool(), "history"),
    ],
)
def test_order_collections_are_grounded_paginated_and_safe(
    monkeypatch, tool, expected_call
) -> None:
    customer_id = uuid4()
    stored = order(customer_id)
    orders, _ = configure(monkeypatch, stored, [stored])

    result = tool.execute(
        trusted_context(customer_id), PaginationInput(limit=5, offset=2)
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.data.total == 1
    assert result.data.limit == 5 and result.data.offset == 2
    assert orders.calls[0] == (expected_call, customer_id, 5, 2)
    serialized = json.loads(result.model_dump_json())["data"]["orders"][0]
    assert "customer_id" not in serialized
    assert "delivery_address" not in serialized
    assert "id" not in serialized


def test_order_details_verifies_ownership_and_counts_items(monkeypatch) -> None:
    customer_id = uuid4()
    stored = order(customer_id)
    _, items = configure(monkeypatch, stored, items=[item(), item()])

    result = GetOrderDetailsTool().execute(
        trusted_context(customer_id), OrderNumberInput(order_number="ORD-10025")
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.data.order_number == "ORD-10025"
    assert result.data.item_count == 2
    assert "delivery_address" not in result.data.model_dump()
    assert items.calls == []


def test_order_items_are_grounded_and_calculate_line_total(monkeypatch) -> None:
    customer_id = uuid4()
    stored = order(customer_id)
    _, items = configure(monkeypatch, stored, items=[item()])

    result = GetOrderItemsTool().execute(
        trusted_context(customer_id),
        OrderItemsInput(order_number="ORD-10025", limit=10),
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.data.items[0].line_total == Decimal("7.00")
    assert result.data.items[0].product_name == "Milk"
    assert items.calls == [(stored.id, 10, 0)]


@pytest.mark.parametrize("tool,input_model", [
    (ListCurrentOrdersTool(), PaginationInput()),
    (ListOrderHistoryTool(), PaginationInput()),
    (GetOrderDetailsTool(), OrderNumberInput(order_number="ORD-10025")),
    (GetOrderItemsTool(), OrderItemsInput(order_number="ORD-10025")),
])
def test_missing_identity_fails_without_database_access(
    monkeypatch, tool, input_model
) -> None:
    monkeypatch.setattr(
        capabilities,
        "get_session_factory",
        lambda: pytest.fail("database must not be accessed"),
    )

    result = tool.execute(trusted_context(), input_model)

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "customer_identity_required"


@pytest.mark.parametrize("tool,input_model", [
    (GetOrderDetailsTool(), OrderNumberInput(order_number="ORD-10025")),
    (GetOrderItemsTool(), OrderItemsInput(order_number="ORD-10025")),
])
def test_missing_or_unowned_order_returns_non_disclosing_failure(
    monkeypatch, tool, input_model
) -> None:
    configure(monkeypatch, order(uuid4()))

    result = tool.execute(trusted_context(uuid4()), input_model)

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "order_not_found"


def test_missing_customer_returns_business_failure_for_collections(monkeypatch) -> None:
    configure(monkeypatch, None, customer_exists=False)

    result = ListCurrentOrdersTool().execute(
        trusted_context(uuid4()), PaginationInput()
    )

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "customer_not_found"

