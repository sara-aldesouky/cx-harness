"""Small factories for model integration tests."""

from datetime import datetime, timezone
from decimal import Decimal
from itertools import count

from sqlalchemy.orm import Session

from app.database.models import (
    Conversation,
    Customer,
    Delivery,
    DeliveryEvent,
    Evaluation,
    Message,
    KnowledgeArticle,
    KnowledgeArticleVersion,
    ModelRun,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
    Refund,
    RefundEligibility,
    RefundEvent,
    ToolCall,
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


def create_knowledge_article(session: Session, **overrides: object) -> KnowledgeArticle:
    number = next(_sequence)
    values = {"slug": f"faq-{number}", "category": "faq", "language": "en", "is_active": True}
    values.update(overrides); article = KnowledgeArticle(**values); session.add(article); session.flush(); return article


def create_knowledge_version(session: Session, article: KnowledgeArticle, **overrides: object) -> KnowledgeArticleVersion:
    values = {"article": article, "version": "1.0", "title": "Approved FAQ", "content": "This is approved customer guidance.", "is_published": True, "published_at": datetime(2026, 7, 25, 9, tzinfo=timezone.utc)}
    values.update(overrides); version = KnowledgeArticleVersion(**values); session.add(version); session.flush(); return version


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


def create_delivery(
    session: Session, order: Order, **overrides: object
) -> Delivery:
    values = {
        "order": order,
        "status": "scheduled",
        "estimated_delivery_time": datetime(2026, 7, 25, 14, tzinfo=timezone.utc),
        "window_start": datetime(2026, 7, 25, 13, tzinfo=timezone.utc),
        "window_end": datetime(2026, 7, 25, 15, tzinfo=timezone.utc),
    }
    values.update(overrides)
    delivery = Delivery(**values)
    session.add(delivery)
    session.flush()
    return delivery


def create_delivery_event(
    session: Session, delivery: Delivery, **overrides: object
) -> DeliveryEvent:
    values = {
        "delivery": delivery,
        "event_type": "scheduled",
        "public_description": "Your delivery has been scheduled.",
        "occurred_at": datetime(2026, 7, 25, 10, tzinfo=timezone.utc),
    }
    values.update(overrides)
    event = DeliveryEvent(**values)
    session.add(event)
    session.flush()
    return event


def create_payment(
    session: Session, order: Order, **overrides: object
) -> Payment:
    values = {
        "order": order,
        "status": "succeeded",
        "method_type": "card",
        "amount": Decimal("25.00"),
        "currency": "EGP",
    }
    values.update(overrides)
    payment = Payment(**values)
    session.add(payment)
    session.flush()
    return payment


def create_payment_event(
    session: Session, payment: Payment, **overrides: object
) -> PaymentEvent:
    values = {
        "payment": payment,
        "event_type": "captured",
        "public_description": "Your payment was successful.",
        "occurred_at": datetime(2026, 7, 25, 10, tzinfo=timezone.utc),
    }
    values.update(overrides)
    event = PaymentEvent(**values)
    session.add(event)
    session.flush()
    return event


def create_refund(session: Session, payment: Payment, **overrides: object) -> Refund:
    values = {
        "payment": payment,
        "status": "completed",
        "amount": Decimal("25.00"),
        "currency": "EGP",
        "public_reason": "Refund completed.",
        "requested_at": datetime(2026, 7, 25, 11, tzinfo=timezone.utc),
        "processed_at": datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
    }
    values.update(overrides)
    refund = Refund(**values)
    session.add(refund)
    session.flush()
    return refund


def create_refund_event(session: Session, refund: Refund, **overrides: object) -> RefundEvent:
    values = {
        "refund": refund,
        "event_type": "completed",
        "public_description": "Your refund was completed.",
        "occurred_at": datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
    }
    values.update(overrides)
    event = RefundEvent(**values)
    session.add(event)
    session.flush()
    return event


def create_refund_eligibility(
    session: Session, order: Order, **overrides: object
) -> RefundEligibility:
    values = {
        "order": order,
        "status": "eligible",
        "public_reason": "This order is within the refund eligibility window.",
        "assessed_at": datetime(2026, 7, 25, 13, tzinfo=timezone.utc),
    }
    values.update(overrides)
    assessment = RefundEligibility(**values)
    session.add(assessment)
    session.flush()
    return assessment


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


def create_tool_call(
    session: Session,
    model_run: ModelRun,
    **overrides: object,
) -> ToolCall:
    values = {
        "model_run": model_run,
        "tool_name": "get_order_status",
        "status": "completed",
        "input_json": {"order_id": "TEST-ORDER"},
        "output_json": {"status": "preparing"},
        "success": True,
        "latency_ms": 25,
    }
    values.update(overrides)
    tool_call = ToolCall(**values)
    session.add(tool_call)
    session.flush()
    return tool_call


def create_evaluation(
    session: Session,
    model_run: ModelRun,
    **overrides: object,
) -> Evaluation:
    number = next(_sequence)
    values = {
        "model_run": model_run,
        "evaluator_type": "automatic",
        "evaluator_name": f"rule_based_{number}",
        "intent_score": Decimal("4.00"),
        "tool_score": Decimal("4.00"),
        "overall_score": Decimal("4.00"),
        "passed": True,
        "details_json": {"rule": "synthetic"},
    }
    values.update(overrides)
    evaluation = Evaluation(**values)
    session.add(evaluation)
    session.flush()
    return evaluation
