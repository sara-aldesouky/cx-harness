"""PostgreSQL-backed runtime integration for approved Stage 10 capabilities."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from decimal import Decimal
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

import app.tools.customer_capabilities as customer_capabilities
import app.tools.delivery_capabilities as delivery_capabilities
import app.tools.order_capabilities as order_capabilities
import app.tools.payment_capabilities as payment_capabilities
import app.tools.knowledge_capabilities as knowledge_capabilities
import app.tools.refund_capabilities as refund_capabilities
from app.config.settings import Settings
from app.database.models import (
    Customer,
    Delivery,
    DeliveryEvent,
    Order,
    KnowledgeArticle,
    KnowledgeArticleVersion,
    OrderItem,
    Payment,
    PaymentEvent,
    Refund,
    RefundEligibility,
    RefundEvent,
    ToolCall,
)
from app.harness.context import ConversationContext, ConversationMessage, ConversationRole
from app.harness.tool_loop_runtime import (
    DEFAULT_BUSINESS_TOOL_CLASSES,
    build_model_tool_loop,
)
from app.services.model_tool_loop_service import ModelToolLoopTermination
from app.tools.context import ExecutionContext
from tests.models.factories import (
    create_customer,
    create_delivery,
    create_delivery_event,
    create_order,
    create_knowledge_article,
    create_knowledge_version,
    create_order_item,
    create_payment,
    create_payment_event,
    create_refund,
    create_refund_eligibility,
    create_refund_event,
)


pytestmark = pytest.mark.integration


APPROVED_TOOL_NAMES = {
    "get_customer_profile",
    "get_customer_summary",
    "get_order_status",
    "list_current_orders",
    "get_order_details",
    "list_order_history",
    "get_order_items",
    "get_delivery_status",
    "get_delivery_eta",
    "get_delivery_window",
    "get_latest_delivery_event",
    "get_delivery_history",
    "get_payment_status",
    "get_payment_method",
    "get_payment_summary",
    "get_payment_history",
    "get_latest_payment_event",
    "get_refund_status",
    "get_refund_summary",
    "get_refund_history",
    "get_latest_refund_event",
    "check_refund_eligibility",
    "search_knowledge",
    "get_policy",
    "get_faq_answer",
    "list_related_articles",
}


@pytest.fixture
def business_records(test_session_factory):  # type: ignore[no-untyped-def]
    """Commit disposable source data so independently scoped tools can read it."""

    with test_session_factory.begin() as session:
        customer = create_customer(
            session,
            first_name="Runtime",
            last_name="Customer",
            preferred_language="ar",
        )
        current = create_order(
            session,
            customer,
            order_number="ORD-10025",
            status="preparing",
            payment_status="paid",
            total_amount=Decimal("15.00"),
        )
        history = create_order(
            session,
            customer,
            order_number="ORD-10018",
            status="delivered",
            payment_status="paid",
            total_amount=Decimal("20.00"),
        )
        create_order_item(
            session,
            current,
            product_name="Milk",
            quantity=2,
            unit_price=Decimal("3.50"),
        )
        create_order_item(
            session,
            current,
            product_name="Bread",
            quantity=1,
            unit_price=Decimal("2.00"),
            item_status="missing",
        )
        delivery = create_delivery(session, current, status="delayed")
        create_delivery_event(
            session,
            delivery,
            event_type="out_for_delivery",
            public_description="Your order is on its way.",
            occurred_at=datetime(2026, 7, 25, 10, tzinfo=timezone.utc),
        )
        payment = create_payment(session, current, status="succeeded")
        create_payment(
            session,
            history,
            status="failed",
            failure_reason_public="The payment provider declined the charge.",
        )
        create_payment_event(
            session,
            payment,
            event_type="authorized",
            public_description="Your payment was authorized.",
            occurred_at=datetime(2026, 7, 25, 9, tzinfo=timezone.utc),
        )
        refund = create_refund(
            session, payment, amount=Decimal("15.00"), status="completed"
        )
        create_refund_event(session, refund)
        create_refund_eligibility(session, current)
        policy = create_knowledge_article(session, slug="refund-policy", category="policy")
        create_knowledge_version(session, policy, content="Refunds take three to five business days.")
        faq = create_knowledge_article(session, slug="delivery-hours", category="faq")
        create_knowledge_version(session, faq, title="Delivery hours", content="Delivery is available from 8 AM to 10 PM.")
        related = create_knowledge_article(session, slug="missing-items", category="faq")
        create_knowledge_version(session, related, content="Contact customer care about missing items.")
        cancellation = create_knowledge_article(session, slug="order-cancellation", category="policy")
        create_knowledge_version(session, cancellation, content="Orders may be cancelled before preparation begins.")
        failed_payment = create_knowledge_article(session, slug="failed-payments", category="faq")
        create_knowledge_version(session, failed_payment, content="A failed payment does not confirm an order.")
        processing = create_knowledge_article(session, slug="refund-processing-time", category="policy")
        create_knowledge_version(session, processing, content="Approved refunds normally take three to five business days.")
        address_change = create_knowledge_article(session, slug="delivery-address-changes", category="policy")
        create_knowledge_version(session, address_change, content="An address may be changed before dispatch when supported.")
        create_payment_event(
            session,
            payment,
            event_type="captured",
            public_description="Your payment was successful.",
            occurred_at=datetime(2026, 7, 25, 10, tzinfo=timezone.utc),
        )
        create_delivery_event(
            session,
            delivery,
            event_type="delivery_attempted",
            public_description="A delivery attempt was made.",
            occurred_at=datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
        )
        customer_id = customer.id
        order_ids = (current.id, history.id)
        knowledge_ids = (
            policy.id, faq.id, related.id, cancellation.id, failed_payment.id,
            processing.id, address_change.id,
        )

    try:
        yield {
            "customer_id": customer_id,
            "current_order_id": order_ids[0],
            "history_order_id": order_ids[1],
        }
    finally:
        with test_session_factory.begin() as session:
            session.execute(delete(KnowledgeArticle).where(KnowledgeArticle.id.in_(knowledge_ids)))
            session.execute(
                delete(ToolCall).where(ToolCall.customer_id == customer_id)
            )
            session.execute(delete(Order).where(Order.id.in_(order_ids)))
            session.execute(delete(Customer).where(Customer.id == customer_id))


def ollama_tool_call(name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def build_http_client(
    tool_name: str, arguments: dict[str, object]
) -> tuple[httpx.Client, list[dict[str, object]]]:
    responses = deque(
        [
            {
                "message": {
                    "role": "assistant",
                    "content": "I will check the approved source.",
                    "tool_calls": [ollama_tool_call(tool_name, arguments)],
                }
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "The requested information was verified.",
                }
            },
        ]
    )
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.popleft())

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def build_multi_tool_http_client(
    calls: tuple[tuple[str, dict[str, object]], ...], final_content: str
) -> tuple[httpx.Client, list[dict[str, object]]]:
    responses = deque(
        [
            {
                "message": {
                    "role": "assistant",
                    "content": "I will verify each required source.",
                    "tool_calls": [
                        ollama_tool_call(name, arguments)
                        for name, arguments in calls
                    ],
                }
            },
            {"message": {"role": "assistant", "content": final_content}},
        ]
    )
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=responses.popleft())

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def business_counts(session_factory) -> dict[str, int]:  # type: ignore[no-untyped-def]
    with session_factory() as session:
        return {
            "customers": session.scalar(
                select(func.count()).select_from(Customer)
            )
            or 0,
            "orders": session.scalar(select(func.count()).select_from(Order)) or 0,
            "order_items": session.scalar(
                select(func.count()).select_from(OrderItem)
            )
            or 0,
            "deliveries": session.scalar(
                select(func.count()).select_from(Delivery)
            )
            or 0,
            "delivery_events": session.scalar(
                select(func.count()).select_from(DeliveryEvent)
            )
            or 0,
            "payments": session.scalar(
                select(func.count()).select_from(Payment)
            )
            or 0,
            "payment_events": session.scalar(
                select(func.count()).select_from(PaymentEvent)
            )
            or 0,
            "refunds": session.scalar(select(func.count()).select_from(Refund)) or 0,
            "refund_events": session.scalar(select(func.count()).select_from(RefundEvent)) or 0,
            "refund_eligibilities": session.scalar(select(func.count()).select_from(RefundEligibility)) or 0,
            "knowledge_articles": session.scalar(select(func.count()).select_from(KnowledgeArticle)) or 0,
            "knowledge_versions": session.scalar(select(func.count()).select_from(KnowledgeArticleVersion)) or 0,
        }


@pytest.mark.parametrize(
    ("tool_name", "arguments", "prompt", "expected_output_key"),
    [
        (
            "get_order_status",
            {"order_id": "ORD-10025"},
            "Where is my order ORD-10025 and when is its delivery?",
            "order_number",
        ),
        (
            "get_customer_profile",
            {"request": "profile"},
            "What language is set on my customer profile?",
            "display_name",
        ),
        (
            "get_customer_summary",
            {"request": "summary"},
            "Summarize my account and order counts.",
            "total_order_count",
        ),
        (
            "list_current_orders",
            {"limit": 10, "offset": 0},
            "What orders are still active?",
            "orders",
        ),
        (
            "get_order_details",
            {"order_number": "ORD-10025"},
            "Give me the order details for reference ORD-10025.",
            "item_count",
        ),
        (
            "list_order_history",
            {"limit": 10, "offset": 0},
            "Show my previous completed order history.",
            "orders",
        ),
        (
            "get_order_items",
            {"order_number": "ORD-10025", "limit": 25, "offset": 0},
            "Which items are in order ORD-10025?",
            "items",
        ),
        (
            "get_delivery_status",
            {"order_number": "ORD-10025"},
            "Is delivery for order ORD-10025 delayed?",
            "status",
        ),
        (
            "get_delivery_eta",
            {"order_number": "ORD-10025"},
            "When will delivery for order ORD-10025 arrive?",
            "estimated_delivery",
        ),
        (
            "get_delivery_window",
            {"order_number": "ORD-10025"},
            "What is the delivery window for order ORD-10025?",
            "window_start",
        ),
        (
            "get_latest_delivery_event",
            {"order_number": "ORD-10025"},
            "What is the latest delivery update for order ORD-10025?",
            "event",
        ),
        (
            "get_delivery_history",
            {"order_number": "ORD-10025", "limit": 10, "offset": 0},
            "Show delivery history for order ORD-10025.",
            "events",
        ),
        (
            "get_payment_status",
            {"order_number": "ORD-10025"},
            "Was payment for order ORD-10025 successful?",
            "status",
        ),
        (
            "get_payment_method",
            {"order_number": "ORD-10025"},
            "How did I pay for order ORD-10025?",
            "method",
        ),
        (
            "get_payment_summary",
            {"order_number": "ORD-10025"},
            "Show the payment summary for order ORD-10025.",
            "amount",
        ),
        (
            "get_payment_history",
            {"order_number": "ORD-10025", "limit": 10, "offset": 0},
            "What payment events happened for order ORD-10025?",
            "events",
        ),
        (
            "get_latest_payment_event",
            {"order_number": "ORD-10025"},
            "What is the latest payment event for order ORD-10025?",
            "event",
        ),
        ("get_refund_status", {"order_number": "ORD-10025"}, "Was my refund completed for order ORD-10025?", "status"),
        ("get_refund_summary", {"order_number": "ORD-10025"}, "How much was refunded for order ORD-10025?", "amount"),
        ("get_refund_history", {"order_number": "ORD-10025", "limit": 10, "offset": 0}, "Show refund history for order ORD-10025.", "refunds"),
        ("get_latest_refund_event", {"order_number": "ORD-10025"}, "What is the latest refund event for order ORD-10025?", "event"),
        ("check_refund_eligibility", {"order_number": "ORD-10025"}, "Is order ORD-10025 eligible for a refund?", "eligible"),
        ("get_policy", {"slug": "refund-policy", "language": "en"}, "What is the refund policy?", "source"),
        ("get_faq_answer", {"slug": "delivery-hours", "language": "en"}, "What are the delivery hours?", "answer"),
        ("search_knowledge", {"query": "Refunds", "language": "en", "limit": 10, "offset": 0}, "Search the policy FAQ for refund timing.", "articles"),
        ("list_related_articles", {"slug": "delivery-hours", "language": "en", "limit": 10, "offset": 0}, "Show related FAQ articles.", "articles"),
    ],
)
def test_complete_runtime_cycle_reads_postgresql_and_continues(
    monkeypatch,
    test_database_url,
    test_session_factory,
    business_records,
    tool_name,
    arguments,
    prompt,
    expected_output_key,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        customer_capabilities,
        "get_session_factory",
        lambda: test_session_factory,
    )
    monkeypatch.setattr(
        order_capabilities,
        "get_session_factory",
        lambda: test_session_factory,
    )
    monkeypatch.setattr(
        delivery_capabilities,
        "get_session_factory",
        lambda: test_session_factory,
    )
    monkeypatch.setattr(
        payment_capabilities,
        "get_session_factory",
        lambda: test_session_factory,
    )
    monkeypatch.setattr(
        knowledge_capabilities,
        "get_session_factory",
        lambda: test_session_factory,
    )
    monkeypatch.setattr(
        refund_capabilities,
        "get_session_factory",
        lambda: test_session_factory,
    )
    client, requests = build_http_client(tool_name, arguments)
    before = business_counts(test_session_factory)
    loop = build_model_tool_loop(
        app_settings=Settings(database_url=test_database_url),
        database_session_factory=test_session_factory,
        ollama_client=client,
    )

    try:
        result = loop.run(
            provider_name="ollama",
            model_name="qwen3:8b",
            context=ConversationContext(
                system_instructions="Use approved tools for business information.",
                messages=(
                    ConversationMessage(
                        role=ConversationRole.USER,
                        content=prompt,
                    ),
                ),
                provider_name="ollama",
                model_name="qwen3:8b",
            ),
            execution_context=ExecutionContext(
                trace_id=uuid4(),
                execution_id=uuid4(),
                customer_id=business_records["customer_id"],
                model_name="qwen3:8b",
            ),
        )
    finally:
        loop.close()

    assert result.termination_reason is ModelToolLoopTermination.FINAL_RESPONSE
    assert result.provider_turns == 2
    assert result.tools_executed == 1
    assert result.tool_cycles[0].selection.tool_name == tool_name
    outcome = result.tool_cycles[0].execution_outcome
    assert outcome.error is None
    assert expected_output_key in outcome.output
    assert result.final_response.content == "The requested information was verified."

    advertised = {
        definition["function"]["name"]
        for definition in requests[0]["tools"]
    }
    assert advertised == APPROVED_TOOL_NAMES
    continuation = requests[1]["messages"]
    tool_messages = [message for message in continuation if message["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_name"] == tool_name
    assert '"status":"success"' in tool_messages[0]["content"]
    assert business_counts(test_session_factory) == before

    with test_session_factory() as session:
        audits = list(
            session.scalars(
                select(ToolCall).where(
                    ToolCall.customer_id == business_records["customer_id"]
                )
            )
        )
    assert len(audits) == 1
    assert audits[0].tool_name == tool_name
    assert audits[0].status == "completed"
    assert audits[0].success is True


def test_default_registration_is_explicit_and_complete() -> None:
    assert {tool.metadata.name for tool in DEFAULT_BUSINESS_TOOL_CLASSES} == (
        APPROVED_TOOL_NAMES
    )


@pytest.mark.parametrize(
    ("prompt", "calls", "final_content"),
    [
        (
            "My order ORD-10025 is delayed. Can I cancel it?",
            (
                ("get_order_details", {"order_number": "ORD-10025"}),
                ("get_delivery_status", {"order_number": "ORD-10025"}),
                ("get_policy", {"slug": "order-cancellation", "language": "en"}),
            ),
            "ORD-10025 is delayed and already preparing. Policy allows cancellation only before preparation, so cancellation is no longer available.",
        ),
        (
            "My payment failed for order ORD-10018 but money was deducted. What happened?",
            (
                ("get_payment_summary", {"order_number": "ORD-10018"}),
                ("get_order_details", {"order_number": "ORD-10018"}),
                ("get_faq_answer", {"slug": "failed-payments", "language": "en"}),
            ),
            "The latest payment record for ORD-10018 failed. A failed payment does not confirm a charge; contact your bank if a pending deduction remains.",
        ),
        (
            "My order ORD-10025 arrived but an item is missing. Under the missing item policy, am I eligible for a refund?",
            (
                ("get_order_items", {"order_number": "ORD-10025", "limit": 25, "offset": 0}),
                ("get_delivery_status", {"order_number": "ORD-10025"}),
                ("check_refund_eligibility", {"order_number": "ORD-10025"}),
                ("get_faq_answer", {"slug": "missing-items", "language": "en"}),
            ),
            "Bread is recorded as missing and the order is eligible for review. Delivery records still show delayed rather than delivered, so that status should be checked.",
        ),
        (
            "Has my refund for order ORD-10025 been approved? How long will it take?",
            (
                ("get_refund_status", {"order_number": "ORD-10025"}),
                ("get_policy", {"slug": "refund-processing-time", "language": "en"}),
            ),
            "The refund for ORD-10025 is completed. Approved refunds normally take three to five business days to appear.",
        ),
        (
            "I changed my address yesterday. Will today's order ORD-10025 arrive there?",
            (
                ("get_customer_profile", {"request": "profile"}),
                ("get_order_details", {"order_number": "ORD-10025"}),
                ("get_delivery_status", {"order_number": "ORD-10025"}),
                ("get_policy", {"slug": "delivery-address-changes", "language": "en"}),
            ),
            "ORD-10025 will use the address currently recorded on the order. I cannot verify address-change history, and the delivery is currently delayed.",
        ),
    ],
)
def test_cross_domain_customer_journeys_are_grounded_and_deterministic(
    monkeypatch,
    test_database_url,
    test_session_factory,
    business_records,
    prompt,
    calls,
    final_content,
) -> None:
    for module in (
        customer_capabilities,
        order_capabilities,
        delivery_capabilities,
        payment_capabilities,
        refund_capabilities,
        knowledge_capabilities,
    ):
        monkeypatch.setattr(module, "get_session_factory", lambda: test_session_factory)
    client, requests = build_multi_tool_http_client(calls, final_content)
    before = business_counts(test_session_factory)
    loop = build_model_tool_loop(
        app_settings=Settings(database_url=test_database_url),
        database_session_factory=test_session_factory,
        ollama_client=client,
    )
    try:
        result = loop.run(
            provider_name="ollama",
            model_name="qwen3:8b",
            context=ConversationContext(
                system_instructions="Combine transactional facts with approved policy evidence.",
                messages=(ConversationMessage(role=ConversationRole.USER, content=prompt),),
                provider_name="ollama",
                model_name="qwen3:8b",
            ),
            execution_context=ExecutionContext(
                trace_id=uuid4(), execution_id=uuid4(),
                customer_id=business_records["customer_id"], model_name="qwen3:8b",
            ),
        )
    finally:
        loop.close()

    expected_names = [name for name, _ in calls]
    assert result.termination_reason is ModelToolLoopTermination.FINAL_RESPONSE
    assert result.provider_turns == 2
    assert result.tools_executed == len(calls)
    assert [cycle.selection.tool_name for cycle in result.tool_cycles] == expected_names
    assert result.final_response.content == final_content
    tool_messages = [message for message in requests[1]["messages"] if message["role"] == "tool"]
    assert [message["tool_name"] for message in tool_messages] == expected_names
    assert len({cycle.selection.call_id for cycle in result.tool_cycles}) == len(calls)
    assert business_counts(test_session_factory) == before


@pytest.mark.parametrize(
    ("prompt", "calls", "expected_executions", "expected_error"),
    [
        (
            "My order ORD-99999 is delayed. Can I cancel it?",
            (
                ("get_order_details", {"order_number": "ORD-99999"}),
                ("get_delivery_status", {"order_number": "ORD-99999"}),
                ("get_policy", {"slug": "order-cancellation", "language": "en"}),
            ),
            1,
            "order_not_found",
        ),
        (
            "Has my refund for order ORD-99999 been approved? How long will it take?",
            (
                ("get_refund_status", {"order_number": "ORD-99999"}),
                ("get_policy", {"slug": "refund-processing-time", "language": "en"}),
            ),
            1,
            "refund_not_found",
        ),
        (
            "Under the missing policy, has my refund for order ORD-10025 been approved?",
            (
                ("get_refund_status", {"order_number": "ORD-10025"}),
                ("get_policy", {"slug": "unavailable-policy", "language": "en"}),
            ),
            2,
            "policy_not_found",
        ),
    ],
)
def test_cross_domain_partial_failures_return_safe_grounding_termination(
    monkeypatch,
    test_database_url,
    test_session_factory,
    business_records,
    prompt,
    calls,
    expected_executions,
    expected_error,
) -> None:
    for module in (
        order_capabilities, delivery_capabilities, refund_capabilities,
        knowledge_capabilities,
    ):
        monkeypatch.setattr(module, "get_session_factory", lambda: test_session_factory)
    client, _ = build_multi_tool_http_client(calls, "This answer must not be returned.")
    loop = build_model_tool_loop(
        app_settings=Settings(database_url=test_database_url),
        database_session_factory=test_session_factory,
        ollama_client=client,
    )
    try:
        result = loop.run(
            provider_name="ollama", model_name="qwen3:8b",
            context=ConversationContext(
                system_instructions="Use approved evidence.",
                messages=(ConversationMessage(role=ConversationRole.USER, content=prompt),),
                provider_name="ollama", model_name="qwen3:8b",
            ),
            execution_context=ExecutionContext(
                trace_id=uuid4(), execution_id=uuid4(),
                customer_id=business_records["customer_id"], model_name="qwen3:8b",
            ),
        )
    finally:
        loop.close()

    assert result.termination_reason is ModelToolLoopTermination.TOOL_BUSINESS_FAILURE
    assert result.final_response.content != "This answer must not be returned."
    assert result.tools_executed == expected_executions
    assert result.error_code == expected_error


def test_unregistered_tool_never_executes(
    monkeypatch,
    test_database_url,
    test_session_factory,
    business_records,
) -> None:
    monkeypatch.setattr(
        customer_capabilities,
        "get_session_factory",
        lambda: test_session_factory,
    )
    client, _ = build_http_client(
        "delete_customer", {"request": "unsupported"}
    )
    loop = build_model_tool_loop(
        app_settings=Settings(database_url=test_database_url),
        database_session_factory=test_session_factory,
        ollama_client=client,
    )
    before = business_counts(test_session_factory)

    try:
        result = loop.run(
            provider_name="ollama",
            model_name="qwen3:8b",
            context=ConversationContext(
                system_instructions="Use registered tools only.",
                messages=(
                    ConversationMessage(
                        role=ConversationRole.USER,
                        content="Perform an unsupported operation.",
                    ),
                ),
                provider_name="ollama",
                model_name="qwen3:8b",
            ),
            execution_context=ExecutionContext(
                trace_id=uuid4(),
                execution_id=uuid4(),
                customer_id=business_records["customer_id"],
                model_name="qwen3:8b",
            ),
        )
    finally:
        loop.close()

    assert result.termination_reason is ModelToolLoopTermination.INVALID_TOOL_CALL
    assert result.tools_executed == 0
    assert business_counts(test_session_factory) == before
    with test_session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ToolCall)
                .where(ToolCall.customer_id == business_records["customer_id"])
            )
            == 0
        )
