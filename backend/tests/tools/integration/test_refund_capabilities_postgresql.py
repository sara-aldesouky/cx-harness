"""PostgreSQL integration for customer-safe Refund read capabilities."""

from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

import app.tools.refund_capabilities as capabilities
from app.database.models import Customer, Order, Payment, Refund, RefundEligibility, RefundEvent
from app.tools.context import ExecutionContext
from app.tools.order_capabilities import OrderNumberInput
from app.tools.refund_capabilities import (
    CheckRefundEligibilityTool, GetLatestRefundEventTool, GetRefundHistoryTool,
    GetRefundStatusTool, GetRefundSummaryTool, RefundHistoryInput,
)
from app.tools.result import ToolStatus
from tests.models.factories import (
    create_customer, create_order, create_payment, create_refund,
    create_refund_eligibility, create_refund_event,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def refund_records(test_session_factory):  # type: ignore[no-untyped-def]
    with test_session_factory.begin() as session:
        customer = create_customer(session)
        full_order = create_order(session, customer, order_number="ORD-60001", total_amount=Decimal("25"))
        payment = create_payment(session, full_order, amount=Decimal("25"))
        full = create_refund(session, payment, amount=Decimal("25"))
        create_refund_event(session, full, event_type="requested", occurred_at=datetime(2026, 7, 25, 11, tzinfo=timezone.utc))
        create_refund_event(session, full, event_type="completed", occurred_at=datetime(2026, 7, 25, 12, tzinfo=timezone.utc))
        create_refund_eligibility(session, full_order)

        multi_order = create_order(session, customer, order_number="ORD-60002")
        multi_payment = create_payment(session, multi_order)
        create_refund(session, multi_payment, amount=Decimal("5"), requested_at=datetime(2026, 7, 20, tzinfo=timezone.utc))
        create_refund(session, multi_payment, amount=Decimal("10"), requested_at=datetime(2026, 7, 21, tzinfo=timezone.utc))

        pending_order = create_order(session, customer, order_number="ORD-60003")
        create_refund(session, create_payment(session, pending_order), status="pending", amount=Decimal("5"), processed_at=None)
        rejected_order = create_order(session, customer, order_number="ORD-60004")
        create_refund(session, create_payment(session, rejected_order), status="rejected", amount=Decimal("5"), public_reason="This item is outside the refund window.")
        ineligible_order = create_order(session, customer, order_number="ORD-60005")
        create_refund_eligibility(session, ineligible_order, status="not_eligible", public_reason="This order is outside the refund window.")
        unavailable_order = create_order(session, customer, order_number="ORD-60006")
        create_refund(session, create_payment(session, unavailable_order), amount=None)
        empty_order = create_order(session, customer, order_number="ORD-60007")
        ids = tuple(order.id for order in (full_order, multi_order, pending_order, rejected_order, ineligible_order, unavailable_order, empty_order))
        customer_id = customer.id
    try:
        yield customer_id
    finally:
        with test_session_factory.begin() as session:
            session.execute(delete(Order).where(Order.id.in_(ids)))
            session.execute(delete(Customer).where(Customer.id == customer_id))


def _context(customer_id):  # type: ignore[no-untyped-def]
    return ExecutionContext(trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id)


def _counts(factory):  # type: ignore[no-untyped-def]
    with factory() as session:
        return tuple(session.scalar(select(func.count()).select_from(m)) or 0 for m in (Order, Payment, Refund, RefundEvent, RefundEligibility))


def test_full_refund_history_latest_eligibility_and_privacy(monkeypatch, test_session_factory, refund_records):
    monkeypatch.setattr(capabilities, "get_session_factory", lambda: test_session_factory)
    trusted, before = _context(refund_records), _counts(test_session_factory)
    status = GetRefundStatusTool().execute(trusted, OrderNumberInput(order_number="ord-60001"))
    summary = GetRefundSummaryTool().execute(trusted, OrderNumberInput(order_number="ORD-60001"))
    history = GetRefundHistoryTool().execute(trusted, RefundHistoryInput(order_number="ORD-60001"))
    latest = GetLatestRefundEventTool().execute(trusted, OrderNumberInput(order_number="ORD-60001"))
    eligibility = CheckRefundEligibilityTool().execute(trusted, OrderNumberInput(order_number="ORD-60001"))
    assert all(r.status is ToolStatus.SUCCESS for r in (status, summary, history, latest, eligibility))
    assert summary.data.refund_type == "full" and summary.data.amount == Decimal("25.00")
    assert latest.data.event.event_type == "completed"
    assert [event.event_type for event in history.data.events] == ["completed", "requested"]
    assert history.data.event_total == 2
    assert eligibility.data.eligible is True
    serialized = json.dumps(history.model_dump(mode="json"))
    for forbidden in ("refund_id", "payment_id", "processor", "transaction", "token", '"id"'):
        assert forbidden not in serialized
    assert _counts(test_session_factory) == before


def test_partial_and_multiple_refunds(monkeypatch, test_session_factory, refund_records):
    monkeypatch.setattr(capabilities, "get_session_factory", lambda: test_session_factory)
    result = GetRefundHistoryTool().execute(_context(refund_records), RefundHistoryInput(order_number="ORD-60002"))
    assert result.status is ToolStatus.SUCCESS and result.data.total == 2
    assert [item.amount for item in result.data.refunds] == [Decimal("10.00"), Decimal("5.00")]
    assert all(item.refund_type == "partial" for item in result.data.refunds)


@pytest.mark.parametrize(("tool", "order", "code"), [
    (GetRefundStatusTool(), "ORD-60003", "refund_pending"),
    (GetRefundStatusTool(), "ORD-60004", "refund_rejected"),
    (GetRefundSummaryTool(), "ORD-60006", "refund_amount_unavailable"),
    (GetRefundStatusTool(), "ORD-60007", "refund_not_found"),
    (GetRefundHistoryTool(), "ORD-60007", "refund_history_empty"),
    (GetLatestRefundEventTool(), "ORD-60007", "refund_history_empty"),
    (CheckRefundEligibilityTool(), "ORD-60005", "refund_not_eligible"),
])
def test_structured_failures(monkeypatch, test_session_factory, refund_records, tool, order, code):
    monkeypatch.setattr(capabilities, "get_session_factory", lambda: test_session_factory)
    input_model = RefundHistoryInput(order_number=order) if isinstance(tool, GetRefundHistoryTool) else OrderNumberInput(order_number=order)
    result = tool.execute(_context(refund_records), input_model)
    assert result.status is ToolStatus.FAILURE and result.error.error_code == code


def test_cross_customer_and_missing_identity(monkeypatch, test_session_factory, refund_records):
    monkeypatch.setattr(capabilities, "get_session_factory", lambda: test_session_factory)
    hidden = GetRefundSummaryTool().execute(_context(uuid4()), OrderNumberInput(order_number="ORD-60001"))
    missing = GetRefundSummaryTool().execute(_context(None), OrderNumberInput(order_number="ORD-60001"))
    assert hidden.error.error_code == "refund_not_found"
    assert missing.error.error_code == "customer_identity_required"
