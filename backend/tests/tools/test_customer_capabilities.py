"""Unit tests for read-only Customer domain capabilities."""

from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

import app.tools.customer_capabilities as capabilities
from app.tools import (
    CustomerProfileInput,
    CustomerSummaryInput,
    ExecutionContext,
    GetCustomerProfileTool,
    GetCustomerSummaryTool,
    ToolCategory,
    ToolStatus,
)


class FakeSession:
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return None


class FakeCustomerRepository:
    def __init__(self, customer):  # type: ignore[no-untyped-def]
        self.customer = customer
        self.requested_id = None

    def get_by_id(self, customer_id):  # type: ignore[no-untyped-def]
        self.requested_id = customer_id
        return self.customer


class FakeOrderRepository:
    def __init__(self) -> None:
        self.requested_ids: list[UUID] = []

    def count_current_by_customer_id(self, customer_id: UUID) -> int:
        self.requested_ids.append(customer_id)
        return 2

    def count_history_by_customer_id(self, customer_id: UUID) -> int:
        self.requested_ids.append(customer_id)
        return 4

    def count(self, *, customer_id: UUID) -> int:
        self.requested_ids.append(customer_id)
        return 6


def trusted_context(customer_id=None):  # type: ignore[no-untyped-def]
    return ExecutionContext(
        trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id
    )


def customer(customer_id):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        id=customer_id,
        first_name="Sara",
        last_name="Customer",
        phone="+201000000000",
        email="private@example.test",
        preferred_language="ar",
        is_active=True,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def configure(monkeypatch, stored_customer):  # type: ignore[no-untyped-def]
    session = FakeSession()
    customers = FakeCustomerRepository(stored_customer)
    orders = FakeOrderRepository()
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: lambda: session
    )
    monkeypatch.setattr(
        capabilities, "CustomerRepository", lambda received: customers
    )
    monkeypatch.setattr(capabilities, "OrderRepository", lambda received: orders)
    return customers, orders


def test_customer_capability_inputs_are_explicit_strict_and_immutable() -> None:
    value = CustomerProfileInput(request="profile")
    assert value.model_dump(mode="json") == {"request": "profile"}
    with pytest.raises(ValidationError):
        CustomerProfileInput(request="summary")
    with pytest.raises(ValidationError):
        CustomerSummaryInput(request="summary", customer_id=str(uuid4()))
    with pytest.raises(ValidationError):
        value.unexpected = "value"


def test_customer_metadata_is_read_only_and_identity_bound() -> None:
    for tool in (GetCustomerProfileTool, GetCustomerSummaryTool):
        assert tool.metadata.category is ToolCategory.CUSTOMER
        assert tool.metadata.is_read_only
        assert tool.metadata.requires_customer_identity
        assert tool.metadata.requires_order_ownership is False


def test_profile_returns_safe_projection_without_contact_details(monkeypatch) -> None:
    customer_id = uuid4()
    customers, _ = configure(monkeypatch, customer(customer_id))

    result = GetCustomerProfileTool().execute(
        trusted_context(customer_id), CustomerProfileInput(request="profile")
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.data.display_name == "Sara Customer"
    assert result.data.preferred_language == "ar"
    serialized = json.loads(result.model_dump_json())
    assert "phone" not in serialized["data"]
    assert "email" not in serialized["data"]
    assert "id" not in serialized["data"]
    assert customers.requested_id == customer_id


def test_summary_uses_repositories_for_grounded_counts(monkeypatch) -> None:
    customer_id = uuid4()
    _, orders = configure(monkeypatch, customer(customer_id))

    result = GetCustomerSummaryTool().execute(
        trusted_context(customer_id), CustomerSummaryInput(request="summary")
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.data.current_order_count == 2
    assert result.data.completed_order_count == 4
    assert result.data.total_order_count == 6
    assert orders.requested_ids == [customer_id, customer_id, customer_id]


@pytest.mark.parametrize(
    ("tool", "input_model"),
    [
        (GetCustomerProfileTool(), CustomerProfileInput(request="profile")),
        (GetCustomerSummaryTool(), CustomerSummaryInput(request="summary")),
    ],
)
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


@pytest.mark.parametrize(
    ("tool", "input_model"),
    [
        (GetCustomerProfileTool(), CustomerProfileInput(request="profile")),
        (GetCustomerSummaryTool(), CustomerSummaryInput(request="summary")),
    ],
)
def test_missing_customer_returns_business_failure(
    monkeypatch, tool, input_model
) -> None:
    configure(monkeypatch, None)

    result = tool.execute(trusted_context(uuid4()), input_model)

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == "customer_not_found"
