"""Database constraint integration tests."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.models import Conversation, Customer, Message, ModelRun, Order, OrderItem
from tests.models.factories import (
    create_conversation,
    create_customer,
    create_message,
    create_order,
)


def assert_rejected(db_session, instance) -> None:
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(instance)
            db_session.flush()


def test_duplicate_customer_email_is_rejected(db_session):
    original = create_customer(db_session)

    assert_rejected(
        db_session,
        Customer(
            first_name="Duplicate",
            last_name="Email",
            phone="+201099999991",
            email=original.email,
        ),
    )


def test_duplicate_customer_phone_is_rejected(db_session):
    original = create_customer(db_session)

    assert_rejected(
        db_session,
        Customer(
            first_name="Duplicate",
            last_name="Phone",
            phone=original.phone,
            email="different@example.test",
        ),
    )


@pytest.mark.parametrize("field,value", [("status", "invalid"), ("total_amount", -1)])
def test_invalid_order_values_are_rejected(db_session, field, value):
    customer = create_customer(db_session)
    values = {
        "customer_id": customer.id,
        "order_number": f"INVALID-{field}",
        "status": "pending",
        "payment_status": "paid",
        "total_amount": Decimal("10.00"),
        "delivery_address": "Test address",
    }
    values[field] = value

    assert_rejected(db_session, Order(**values))


@pytest.mark.parametrize("field,value", [("quantity", 0), ("unit_price", -1)])
def test_invalid_order_item_values_are_rejected(db_session, field, value):
    customer = create_customer(db_session)
    order = create_order(db_session, customer)
    values = {
        "order_id": order.id,
        "product_name": "Invalid item",
        "quantity": 1,
        "unit_price": Decimal("10.00"),
        "item_status": "included",
    }
    values[field] = value

    assert_rejected(db_session, OrderItem(**values))


@pytest.mark.parametrize("field,value", [("status", "invalid"), ("channel", "email")])
def test_invalid_conversation_values_are_rejected(db_session, field, value):
    customer = create_customer(db_session)
    values = {
        "customer_id": customer.id,
        "status": "open",
        "channel": "web",
    }
    values[field] = value

    assert_rejected(db_session, Conversation(**values))


def test_message_sequence_is_unique_per_conversation(db_session):
    customer = create_customer(db_session)
    conversation = create_conversation(db_session, customer)
    create_message(db_session, conversation, sequence_number=1)

    assert_rejected(
        db_session,
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content="Duplicate sequence",
            language="english",
            sequence_number=1,
        ),
    )


@pytest.mark.parametrize("content", ["", "   "])
def test_empty_message_content_is_rejected(db_session, content):
    customer = create_customer(db_session)
    conversation = create_conversation(db_session, customer)

    assert_rejected(
        db_session,
        Message(
            conversation_id=conversation.id,
            role="user",
            content=content,
            language="english",
            sequence_number=1,
        ),
    )


def valid_model_run(conversation, **overrides):
    values = {
        "conversation_id": conversation.id,
        "provider": "gemini",
        "model_name": "test-model",
        "status": "completed",
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
        "latency_ms": 1,
        "temperature": Decimal("0.50"),
        "success": True,
    }
    values.update(overrides)
    return ModelRun(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "invalid"},
        {"status": "invalid"},
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"total_tokens": -1},
        {"latency_ms": -1},
        {"temperature": Decimal("-0.01")},
        {"temperature": Decimal("2.01")},
    ],
    ids=[
        "provider",
        "status",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "latency",
        "temperature_below_zero",
        "temperature_above_two",
    ],
)
def test_invalid_model_run_values_are_rejected(db_session, overrides):
    customer = create_customer(db_session)
    conversation = create_conversation(db_session, customer)

    assert_rejected(db_session, valid_model_run(conversation, **overrides))
