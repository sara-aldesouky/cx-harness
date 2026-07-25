"""PostgreSQL integration for customer-safe Payment read capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

import app.tools.payment_capabilities as capabilities
from app.database.models import Customer, Order, Payment, PaymentEvent
from app.tools import (
    ExecutionContext,
    GetLatestPaymentEventTool,
    GetPaymentHistoryTool,
    GetPaymentMethodTool,
    GetPaymentStatusTool,
    GetPaymentSummaryTool,
    OrderNumberInput,
    PaymentHistoryInput,
    ToolStatus,
)
from tests.models.factories import (
    create_customer,
    create_order,
    create_payment,
    create_payment_event,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def payment_records(test_session_factory):  # type: ignore[no-untyped-def]
    with test_session_factory.begin() as session:
        customer = create_customer(session)
        order_ids = []

        success_order = create_order(session, customer, order_number="ORD-50001")
        order_ids.append(success_order.id)
        success = create_payment(session, success_order)
        create_payment_event(
            session,
            success,
            event_type="authorized",
            public_description="Your payment was authorized.",
            occurred_at=datetime(2026, 7, 25, 9, tzinfo=timezone.utc),
        )
        create_payment_event(
            session,
            success,
            event_type="captured",
            public_description="Your payment was successful.",
            occurred_at=datetime(2026, 7, 25, 10, tzinfo=timezone.utc),
        )

        pending_order = create_order(session, customer, order_number="ORD-50002")
        order_ids.append(pending_order.id)
        create_payment(session, pending_order, status="pending")

        failed_order = create_order(session, customer, order_number="ORD-50003")
        order_ids.append(failed_order.id)
        create_payment(
            session,
            failed_order,
            status="failed",
            failure_reason_public="The bank declined the payment.",
        )

        refund_order = create_order(session, customer, order_number="ORD-50004")
        order_ids.append(refund_order.id)
        refunded = create_payment(session, refund_order, status="refunded")
        create_payment_event(
            session,
            refunded,
            event_type="refunded",
            public_description="Your payment was refunded.",
        )

        no_method_order = create_order(
            session, customer, order_number="ORD-50005"
        )
        order_ids.append(no_method_order.id)
        create_payment(session, no_method_order, method_type=None)

        empty_order = create_order(session, customer, order_number="ORD-50006")
        order_ids.append(empty_order.id)
        create_payment(session, empty_order)

        customer_id = customer.id
        order_ids = tuple(order_ids)
    try:
        yield customer_id
    finally:
        with test_session_factory.begin() as session:
            session.execute(delete(Order).where(Order.id.in_(order_ids)))
            session.execute(delete(Customer).where(Customer.id == customer_id))


def context(customer_id) -> ExecutionContext:  # type: ignore[no-untyped-def]
    return ExecutionContext(
        trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id
    )


def counts(session_factory) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    with session_factory() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (Order, Payment, PaymentEvent)
        )


def test_success_method_summary_history_and_latest_are_private_and_read_only(
    monkeypatch, test_session_factory, payment_records
) -> None:
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: test_session_factory
    )
    trusted = context(payment_records)
    order_input = OrderNumberInput(order_number="ord-50001")
    before = counts(test_session_factory)

    status = GetPaymentStatusTool().execute(trusted, order_input)
    method = GetPaymentMethodTool().execute(trusted, order_input)
    summary = GetPaymentSummaryTool().execute(trusted, order_input)
    latest = GetLatestPaymentEventTool().execute(trusted, order_input)
    history = GetPaymentHistoryTool().execute(
        trusted, PaymentHistoryInput(order_number="ORD-50001")
    )

    assert all(
        result.status is ToolStatus.SUCCESS
        for result in (status, method, summary, latest, history)
    )
    assert status.data.status == "succeeded"
    assert method.data.method == "card"
    assert summary.data.amount > 0 and summary.data.currency == "EGP"
    assert latest.data.event.event_type == "captured"
    assert [event.event_type for event in history.data.events] == [
        "captured",
        "authorized",
    ]
    serialized = json.dumps(history.model_dump(mode="json"))
    for forbidden in ("payment_id", "transaction", "token", "card_number", '"id"'):
        assert forbidden not in serialized
    assert counts(test_session_factory) == before


def test_pending_failed_and_refunded_states(
    monkeypatch, test_session_factory, payment_records
) -> None:
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: test_session_factory
    )
    trusted = context(payment_records)

    pending = GetPaymentStatusTool().execute(
        trusted, OrderNumberInput(order_number="ORD-50002")
    )
    failed = GetPaymentStatusTool().execute(
        trusted, OrderNumberInput(order_number="ORD-50003")
    )
    failed_summary = GetPaymentSummaryTool().execute(
        trusted, OrderNumberInput(order_number="ORD-50003")
    )
    refunded = GetPaymentStatusTool().execute(
        trusted, OrderNumberInput(order_number="ORD-50004")
    )

    assert pending.error.error_code == "payment_pending"
    assert failed.error.error_code == "payment_failed"
    assert failed.error.public_message == "The bank declined the payment."
    assert failed_summary.data.status == "failed"
    assert refunded.status is ToolStatus.SUCCESS
    assert refunded.data.status == "refunded"


@pytest.mark.parametrize(
    ("tool", "input_model", "expected_code"),
    [
        (
            GetPaymentStatusTool(),
            OrderNumberInput(order_number="ORD-59999"),
            "payment_not_found",
        ),
        (
            GetPaymentMethodTool(),
            OrderNumberInput(order_number="ORD-50005"),
            "payment_method_unavailable",
        ),
        (
            GetLatestPaymentEventTool(),
            OrderNumberInput(order_number="ORD-50006"),
            "payment_history_empty",
        ),
        (
            GetPaymentHistoryTool(),
            PaymentHistoryInput(order_number="ORD-50006"),
            "payment_history_empty",
        ),
    ],
)
def test_structured_payment_failures(
    monkeypatch,
    test_session_factory,
    payment_records,
    tool,
    input_model,
    expected_code,
) -> None:
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: test_session_factory
    )

    result = tool.execute(context(payment_records), input_model)

    assert result.status is ToolStatus.FAILURE
    assert result.error.error_code == expected_code


def test_cross_customer_and_missing_identity_are_private(
    monkeypatch, test_session_factory, payment_records
) -> None:
    monkeypatch.setattr(
        capabilities, "get_session_factory", lambda: test_session_factory
    )

    other = GetPaymentSummaryTool().execute(
        context(uuid4()), OrderNumberInput(order_number="ORD-50001")
    )
    missing = GetPaymentSummaryTool().execute(
        context(None), OrderNumberInput(order_number="ORD-50001")
    )

    assert other.error.error_code == "payment_not_found"
    assert missing.error.error_code == "customer_identity_required"
