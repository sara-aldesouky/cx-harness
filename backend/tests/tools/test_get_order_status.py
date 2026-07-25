"""Unit tests for the first read-only business tool and harness flow."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

import app.tools.get_order_status as tool_module
from app.tools import (
    ExecutionContext,
    GetOrderStatusInput,
    GetOrderStatusOutput,
    GetOrderStatusTool,
    ToolCategory,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    ToolStatus,
)
from tests.tools.audit_fakes import RecordingAuditRepository


class FakeSession:
    def __init__(self) -> None:
        self.entered = False
        self.closed = False

    def __enter__(self) -> FakeSession:
        self.entered = True
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSession:
        return self.session


class FakeOrderRepository:
    def __init__(self, session: FakeSession, order: object = None) -> None:
        self.session = session
        self.order = order
        self.requested_order_id: UUID | None = None
        self.requested_order_number: str | None = None

    def get_by_id(self, order_id: UUID) -> object:
        self.requested_order_id = order_id
        return self.order

    def get_by_order_number(self, order_number: str) -> object:
        self.requested_order_number = order_number
        return self.order


def context(customer_id: UUID | None = None) -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        customer_id=customer_id,
    )


def order(customer_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        customer_id=customer_id,
        order_number="CX-TEST-0001",
        status="dispatched",
        payment_status="paid",
        estimated_delivery_time=datetime(2026, 7, 28, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )


def configure_repository(monkeypatch, stored_order: object):
    session = FakeSession()
    repository = FakeOrderRepository(session, stored_order)
    monkeypatch.setattr(
        tool_module,
        "get_session_factory",
        lambda: FakeSessionFactory(session),
    )
    monkeypatch.setattr(
        tool_module,
        "OrderRepository",
        lambda received_session: (
            repository
            if received_session is session
            else pytest.fail("repository received an unexpected session")
        ),
    )
    return session, repository


def execute_through_harness(
    execution_context: ExecutionContext,
    input_model: GetOrderStatusInput,
) -> ToolResult:
    registry = ToolRegistry()
    registry.register(GetOrderStatusTool)
    return ToolExecutor(registry, RecordingAuditRepository()).execute(
        "get_order_status",
        "1.0.0",
        execution_context,
        input_model,
    )


def test_metadata_describes_one_read_only_owned_order_lookup() -> None:
    metadata = GetOrderStatusTool.metadata

    assert metadata.name == "get_order_status"
    assert metadata.version == "1.0.0"
    assert metadata.category is ToolCategory.ORDER
    assert metadata.is_read_only is True
    assert metadata.requires_customer_identity is True
    assert metadata.requires_order_ownership is True
    assert metadata.requires_policy_check is False


def test_input_contains_only_model_requested_order_id() -> None:
    assert set(GetOrderStatusInput.model_fields) == {"order_id"}
    assert "customer_id" not in GetOrderStatusInput.model_fields
    assert "conversation_id" not in GetOrderStatusInput.model_fields
    assert "trace_id" not in GetOrderStatusInput.model_fields


def test_input_rejects_invalid_order_id() -> None:
    with pytest.raises(ValidationError):
        GetOrderStatusInput(order_id="not-a-uuid")


def test_owned_order_succeeds_through_registry_and_executor(monkeypatch) -> None:
    customer_id = uuid4()
    stored_order = order(customer_id)
    session, repository = configure_repository(monkeypatch, stored_order)
    execution_context = context(customer_id)
    input_model = GetOrderStatusInput(order_id=stored_order.id)

    result = execute_through_harness(execution_context, input_model)

    assert result.status is ToolStatus.SUCCESS
    assert result.error is None
    assert result.data == GetOrderStatusOutput(
        order_number="CX-TEST-0001",
        status="dispatched",
        payment_status="paid",
        estimated_delivery=stored_order.estimated_delivery_time,
        created_at=stored_order.created_at,
    )
    assert repository.requested_order_id == stored_order.id
    assert repository.session is session
    assert session.entered is True
    assert session.closed is True


def test_customer_facing_order_number_is_normalized_and_resolved(monkeypatch) -> None:
    customer_id = uuid4()
    stored_order = order(customer_id)
    _, repository = configure_repository(monkeypatch, stored_order)

    result = execute_through_harness(
        context(customer_id), GetOrderStatusInput(order_id="  cx-test-0001  ")
    )

    assert result.status is ToolStatus.SUCCESS
    assert repository.requested_order_number == "CX-TEST-0001"
    assert repository.requested_order_id is None


def test_missing_order_returns_business_failure(monkeypatch) -> None:
    _, repository = configure_repository(monkeypatch, None)
    order_id = uuid4()

    result = execute_through_harness(
        context(uuid4()), GetOrderStatusInput(order_id=order_id)
    )

    assert result.status is ToolStatus.FAILURE
    assert result.data is None
    assert result.error is not None
    assert result.error.error_code == "order_not_found"
    assert repository.requested_order_id == order_id


def test_customer_who_does_not_own_order_gets_business_failure(monkeypatch) -> None:
    stored_order = order(uuid4())
    configure_repository(monkeypatch, stored_order)

    result = execute_through_harness(
        context(uuid4()), GetOrderStatusInput(order_id=stored_order.id)
    )

    assert result.status is ToolStatus.FAILURE
    assert result.data is None
    assert result.error is not None
    assert result.error.error_code == "order_access_denied"


def test_missing_trusted_customer_identity_fails_without_database_access(
    monkeypatch,
) -> None:
    accessed_database = False

    def unexpected_session_factory():
        nonlocal accessed_database
        accessed_database = True
        pytest.fail("database must not be accessed without customer identity")

    monkeypatch.setattr(
        tool_module, "get_session_factory", unexpected_session_factory
    )

    result = execute_through_harness(
        context(), GetOrderStatusInput(order_id=uuid4())
    )

    assert result.status is ToolStatus.FAILURE
    assert result.error is not None
    assert result.error.error_code == "customer_identity_required"
    assert accessed_database is False


def test_tool_is_registered_by_name_and_definition_is_json_compatible() -> None:
    registry = ToolRegistry()
    registry.register(GetOrderStatusTool)

    assert registry.get("get_order_status", "1.0.0") is GetOrderStatusTool
    assert json.loads(json.dumps(registry.definitions()))[0]["name"] == (
        "get_order_status"
    )
