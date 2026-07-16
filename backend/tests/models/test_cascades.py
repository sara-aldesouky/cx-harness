"""Foreign-key deletion behavior integration tests."""

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.database.models import Conversation, Customer, Message, ModelRun, Order, OrderItem
from tests.models.factories import (
    create_conversation,
    create_customer,
    create_message,
    create_model_run,
    create_order,
    create_order_item,
)


def test_deleting_conversation_cascades_to_messages_and_model_runs(db_session):
    customer = create_customer(db_session)
    conversation = create_conversation(db_session, customer)
    message = create_message(db_session, conversation)
    model_run = create_model_run(db_session, conversation)
    conversation_id = conversation.id
    message_id = message.id
    model_run_id = model_run.id

    db_session.expire_all()
    db_session.execute(delete(Conversation).where(Conversation.id == conversation_id))
    db_session.flush()

    assert db_session.get(Message, message_id) is None
    assert db_session.get(ModelRun, model_run_id) is None


def test_deleting_order_cascades_items_and_nulls_conversation_reference(db_session):
    customer = create_customer(db_session)
    order = create_order(db_session, customer)
    item = create_order_item(db_session, order)
    conversation = create_conversation(db_session, customer, order)
    order_id = order.id
    item_id = item.id
    conversation_id = conversation.id

    db_session.expire_all()
    db_session.execute(delete(Order).where(Order.id == order_id))
    db_session.flush()

    assert db_session.get(OrderItem, item_id) is None
    assert db_session.get(Conversation, conversation_id).related_order_id is None


def test_deleting_referenced_customer_is_restricted(db_session):
    customer = create_customer(db_session)
    order = create_order(db_session, customer)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(delete(Customer).where(Customer.id == customer.id))
            db_session.flush()

    assert db_session.get(Customer, customer.id) is not None
    assert db_session.get(Order, order.id) is not None


def test_deleting_message_keeps_conversation(db_session):
    customer = create_customer(db_session)
    conversation = create_conversation(db_session, customer)
    message = create_message(db_session, conversation)

    db_session.execute(delete(Message).where(Message.id == message.id))
    db_session.flush()

    assert db_session.get(Conversation, conversation.id) is not None


def test_deleting_model_run_keeps_conversation(db_session):
    customer = create_customer(db_session)
    conversation = create_conversation(db_session, customer)
    model_run = create_model_run(db_session, conversation)

    db_session.execute(delete(ModelRun).where(ModelRun.id == model_run.id))
    db_session.flush()

    assert db_session.scalar(
        select(Conversation).where(Conversation.id == conversation.id)
    ) is not None
