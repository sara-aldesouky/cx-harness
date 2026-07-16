"""Persistence and relationship integration tests."""

from decimal import Decimal

from sqlalchemy import func, select

from app.database.models import (
    Conversation,
    Customer,
    Message,
    ModelRun,
    Order,
    OrderItem,
)
from tests.models.factories import (
    create_conversation,
    create_customer,
    create_message,
    create_model_run,
    create_order,
    create_order_item,
)


def test_customer_persists_with_defaults(db_session):
    customer = create_customer(db_session)

    db_session.refresh(customer)

    assert customer.id is not None
    assert customer.preferred_language == "en"
    assert customer.is_active is True
    assert customer.created_at is not None


def test_customer_has_orders_and_conversations(db_session):
    customer = create_customer(db_session)
    order = create_order(db_session, customer)
    conversation = create_conversation(db_session, customer, order)

    db_session.expire_all()
    persisted = db_session.get(Customer, customer.id)

    assert persisted.orders == [order]
    assert persisted.conversations == [conversation]


def test_order_belongs_to_customer_and_has_items_and_conversations(db_session):
    customer = create_customer(db_session)
    order = create_order(db_session, customer)
    item = create_order_item(db_session, order)
    conversation = create_conversation(db_session, customer, order)

    db_session.expire_all()
    persisted = db_session.get(Order, order.id)

    assert persisted.customer == customer
    assert persisted.items == [item]
    assert persisted.conversations == [conversation]
    assert persisted.total_amount == Decimal("25.00")


def test_order_item_belongs_to_order(db_session):
    customer = create_customer(db_session)
    order = create_order(db_session, customer)
    item = create_order_item(db_session, order)

    db_session.expire_all()

    assert db_session.get(OrderItem, item.id).order == order


def test_conversation_has_complete_relationship_graph(db_session):
    customer = create_customer(db_session)
    order = create_order(db_session, customer)
    conversation = create_conversation(db_session, customer, order)
    first = create_message(db_session, conversation)
    second = create_message(
        db_session,
        conversation,
        role="assistant",
        content="Your order is being prepared.",
        sequence_number=2,
    )
    model_run = create_model_run(db_session, conversation)

    db_session.expire_all()
    persisted = db_session.get(Conversation, conversation.id)

    assert persisted.customer == customer
    assert persisted.related_order == order
    assert persisted.messages == [first, second]
    assert persisted.model_runs == [model_run]


def test_message_belongs_to_conversation(db_session):
    customer = create_customer(db_session)
    conversation = create_conversation(db_session, customer)
    message = create_message(db_session, conversation)

    db_session.expire_all()

    assert db_session.get(Message, message.id).conversation == conversation


def test_model_run_belongs_to_conversation(db_session):
    customer = create_customer(db_session)
    conversation = create_conversation(db_session, customer)
    model_run = create_model_run(db_session, conversation)

    db_session.expire_all()

    assert db_session.get(ModelRun, model_run.id).conversation == conversation


def test_nested_transaction_rollback_removes_inserted_graph(db_session):
    transaction = db_session.begin_nested()
    customer = create_customer(db_session)
    order = create_order(db_session, customer)
    create_order_item(db_session, order)
    conversation = create_conversation(db_session, customer, order)
    create_message(db_session, conversation)
    create_model_run(db_session, conversation)

    transaction.rollback()

    for model in (Customer, Order, OrderItem, Conversation, Message, ModelRun):
        count = db_session.scalar(select(func.count()).select_from(model))
        assert count == 0
