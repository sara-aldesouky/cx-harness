"""Small factories for model integration tests."""

from decimal import Decimal
from itertools import count

from sqlalchemy.orm import Session

from app.database.models import (
    Conversation,
    Customer,
    Message,
    ModelRun,
    Order,
    OrderItem,
)


_sequence = count(1)


def create_customer(session: Session, **overrides: object) -> Customer:
    number = next(_sequence)
    values = {
        "first_name": "Test",
        "last_name": f"Customer {number}",
        "phone": f"+201000{number:06d}",
        "email": f"customer{number}@example.test",
        "preferred_language": "en",
    }
    values.update(overrides)
    customer = Customer(**values)
    session.add(customer)
    session.flush()
    return customer


def create_order(
    session: Session, customer: Customer, **overrides: object
) -> Order:
    number = next(_sequence)
    values = {
        "customer": customer,
        "order_number": f"TEST-{number:06d}",
        "status": "pending",
        "payment_status": "pending",
        "total_amount": Decimal("25.00"),
        "delivery_address": "Test address",
    }
    values.update(overrides)
    order = Order(**values)
    session.add(order)
    session.flush()
    return order


def create_order_item(
    session: Session, order: Order, **overrides: object
) -> OrderItem:
    values = {
        "order": order,
        "product_name": "Test product",
        "quantity": 2,
        "unit_price": Decimal("12.50"),
        "item_status": "included",
    }
    values.update(overrides)
    item = OrderItem(**values)
    session.add(item)
    session.flush()
    return item


def create_conversation(
    session: Session,
    customer: Customer,
    order: Order = None,
    **overrides: object,
) -> Conversation:
    values = {
        "customer": customer,
        "related_order": order,
        "status": "open",
        "channel": "web",
        "active_model": "gemini-2.0-flash",
    }
    values.update(overrides)
    conversation = Conversation(**values)
    session.add(conversation)
    session.flush()
    return conversation


def create_message(
    session: Session,
    conversation: Conversation,
    **overrides: object,
) -> Message:
    values = {
        "conversation": conversation,
        "role": "user",
        "content": "Where is my order?",
        "language": "english",
        "sequence_number": 1,
    }
    values.update(overrides)
    message = Message(**values)
    session.add(message)
    session.flush()
    return message


def create_model_run(
    session: Session,
    conversation: Conversation,
    **overrides: object,
) -> ModelRun:
    values = {
        "conversation": conversation,
        "provider": "gemini",
        "model_name": "gemini-2.0-flash",
        "status": "completed",
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "latency_ms": 100,
        "estimated_cost": Decimal("0.001000"),
        "temperature": Decimal("0.50"),
        "success": True,
    }
    values.update(overrides)
    model_run = ModelRun(**values)
    session.add(model_run)
    session.flush()
    return model_run
