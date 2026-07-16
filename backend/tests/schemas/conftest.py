"""Shared values for response-schema tests."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def now():
    return datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def graph(now):
    customer = SimpleNamespace(
        id=uuid4(),
        first_name="Sara",
        last_name="Test",
        phone="+201000000001",
        email="sara@example.test",
        preferred_language="en",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    order = SimpleNamespace(
        id=uuid4(),
        order_number="TEST-001",
        customer_id=customer.id,
        status="pending",
        payment_status="paid",
        total_amount=Decimal("25.50"),
        delivery_address="Test address",
        estimated_delivery_time=None,
        created_at=now,
        updated_at=now,
        customer=customer,
    )
    conversation = SimpleNamespace(
        id=uuid4(),
        customer_id=customer.id,
        related_order_id=order.id,
        status="open",
        channel="web",
        active_model="gemini-test",
        started_at=now,
        ended_at=None,
        created_at=now,
        updated_at=now,
        customer=customer,
        related_order=order,
    )
    message = SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation.id,
        role="user",
        content="Where is my order?",
        language=None,
        sequence_number=1,
        created_at=now,
    )
    model_run = SimpleNamespace(
        id=uuid4(),
        conversation_id=conversation.id,
        provider="gemini",
        model_name="gemini-test",
        status="completed",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        latency_ms=100,
        estimated_cost=Decimal("0.001000"),
        temperature=Decimal("0.50"),
        success=True,
        error_message=None,
        started_at=now,
        finished_at=None,
        created_at=now,
    )
    tool_call = SimpleNamespace(
        id=uuid4(),
        model_run_id=model_run.id,
        tool_name="get_order_status",
        status="completed",
        input_json={"order_id": "TEST-001"},
        output_json={"status": "pending"},
        success=True,
        latency_ms=25,
        error_message=None,
        requested_at=now,
        started_at=None,
        finished_at=None,
        created_at=now,
    )
    evaluation = SimpleNamespace(
        id=uuid4(),
        model_run_id=model_run.id,
        evaluator_type="automatic",
        evaluator_name="rule_based_v1",
        intent_score=Decimal("4.00"),
        tool_score=Decimal("4.50"),
        tone_score=None,
        arabic_score=None,
        franco_score=None,
        policy_score=Decimal("5.00"),
        resolution_score=None,
        overall_score=Decimal("4.25"),
        passed=True,
        notes=None,
        details_json={"expected_intent": "order_status"},
        evaluated_at=now,
        created_at=now,
    )
    item = SimpleNamespace(
        id=uuid4(),
        order_id=order.id,
        product_name="Test item",
        quantity=2,
        unit_price=Decimal("12.75"),
        item_status="included",
        created_at=now,
    )
    order.items = [item]
    order.conversations = [conversation]
    customer.orders = [order]
    customer.conversations = [conversation]
    conversation.messages = [message]
    conversation.model_runs = [model_run]
    model_run.tool_calls = [tool_call]
    model_run.evaluations = [evaluation]
    return SimpleNamespace(
        customer=customer,
        order=order,
        conversation=conversation,
        message=message,
        model_run=model_run,
        tool_call=tool_call,
        evaluation=evaluation,
        item=item,
    )
