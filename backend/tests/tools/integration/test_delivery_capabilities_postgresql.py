"""PostgreSQL integration for customer-safe Delivery read capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import delete, func, select

import app.tools.delivery_capabilities as capabilities
from app.database.models import Customer, Delivery, DeliveryEvent, Order
from app.tools import (
    DeliveryHistoryInput,
    ExecutionContext,
    GetDeliveryEtaTool,
    GetDeliveryHistoryTool,
    GetDeliveryStatusTool,
    GetDeliveryWindowTool,
    GetLatestDeliveryEventTool,
    OrderNumberInput,
    ToolStatus,
)
from tests.models.factories import (
    create_customer,
    create_delivery,
    create_delivery_event,
    create_order,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def delivery_records(test_session_factory):  # type: ignore[no-untyped-def]
    with test_session_factory.begin() as session:
        customer = create_customer(session)
        order = create_order(session, customer, order_number="ORD-30001")
        delivery = create_delivery(session, order, status="delayed")
        create_delivery_event(
            session,
            delivery,
            event_type="out_for_delivery",
            public_description="Your order is on its way.",
            occurred_at=datetime(2026, 7, 25, 10, tzinfo=timezone.utc),
        )
        create_delivery_event(
            session,
            delivery,
            event_type="delivery_attempted",
            public_description="A delivery attempt was made.",
            occurred_at=datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
        )
        no_eta_order = create_order(session, customer, order_number="ORD-30002")
        create_delivery(
            session,
            no_eta_order,
            estimated_delivery_time=None,
            window_start=None,
            window_end=None,
        )
        empty_order = create_order(session, customer, order_number="ORD-30003")
        create_delivery(session, empty_order, status="scheduled")
        not_started_order = create_order(
            session, customer, order_number="ORD-30004"
        )
        create_delivery(
            session,
            not_started_order,
            status="not_started",
            estimated_delivery_time=None,
            window_start=None,
            window_end=None,
        )
        customer_id = customer.id
        order_ids = (order.id, no_eta_order.id, empty_order.id, not_started_order.id)
    try:
        yield customer_id
    finally:
        with test_session_factory.begin() as session:
            session.execute(delete(Order).where(Order.id.in_(order_ids)))
            session.execute(delete(Customer).where(Customer.id == customer_id))


def context(customer_id):  # type: ignore[no-untyped-def]
    from uuid import uuid4

    return ExecutionContext(
        trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id
    )


def counts(session_factory) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    with session_factory() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (Order, Delivery, DeliveryEvent)
        )


def test_all_delivery_reads_are_grounded_private_and_read_only(
    monkeypatch, test_session_factory, delivery_records
) -> None:
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: test_session_factory
    )
    trusted = context(delivery_records)
    order_input = OrderNumberInput(order_number="ord-30001")
    before = counts(test_session_factory)

    status = GetDeliveryStatusTool().execute(trusted, order_input)
    eta = GetDeliveryEtaTool().execute(trusted, order_input)
    window = GetDeliveryWindowTool().execute(trusted, order_input)
    latest = GetLatestDeliveryEventTool().execute(trusted, order_input)
    history = GetDeliveryHistoryTool().execute(
        trusted,
        DeliveryHistoryInput(order_number="ORD-30001", limit=10, offset=0),
    )

    assert all(
        result.status is ToolStatus.SUCCESS
        for result in (status, eta, window, latest, history)
    )
    assert status.data.status == "delayed" and status.data.is_delayed is True
    assert eta.data.estimated_delivery is not None
    assert window.data.window_start < window.data.window_end
    assert latest.data.event.event_type == "delivery_attempted"
    assert [event.event_type for event in history.data.events] == [
        "delivery_attempted",
        "out_for_delivery",
    ]
    assert history.data.total == 2
    serialized = json.dumps(history.model_dump(mode="json"))
    assert "delivery_id" not in serialized and '"id"' not in serialized
    assert counts(test_session_factory) == before


@pytest.mark.parametrize(
    ("tool", "order_number", "expected_code"),
    [
        (GetDeliveryStatusTool(), "ORD-99999", "delivery_not_found"),
        (GetDeliveryEtaTool(), "ORD-30002", "eta_unavailable"),
        (
            GetDeliveryWindowTool(),
            "ORD-30002",
            "delivery_window_unavailable",
        ),
        (
            GetLatestDeliveryEventTool(),
            "ORD-30003",
            "delivery_history_empty",
        ),
        (GetDeliveryEtaTool(), "ORD-30004", "delivery_not_started"),
    ],
)
def test_delivery_business_failures(
    monkeypatch,
    test_session_factory,
    delivery_records,
    tool,
    order_number,
    expected_code,
) -> None:
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: test_session_factory
    )

    result = tool.execute(
        context(delivery_records), OrderNumberInput(order_number=order_number)
    )

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == expected_code


def test_delivery_history_empty_and_missing_identity(
    monkeypatch, test_session_factory, delivery_records
) -> None:
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: test_session_factory
    )
    empty = GetDeliveryHistoryTool().execute(
        context(delivery_records),
        DeliveryHistoryInput(order_number="ORD-30003"),
    )
    missing_identity = GetDeliveryStatusTool().execute(
        context(None), OrderNumberInput(order_number="ORD-30001")
    )

    assert empty.error.error_code == "delivery_history_empty"
    assert missing_identity.error.error_code == "customer_identity_required"


def test_other_customer_cannot_discover_delivery(
    monkeypatch, test_session_factory, delivery_records
) -> None:
    from uuid import uuid4

    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: test_session_factory
    )

    result = GetDeliveryStatusTool().execute(
        context(uuid4()), OrderNumberInput(order_number="ORD-30001")
    )

    assert result.error.error_code == "delivery_not_found"
