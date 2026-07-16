"""Customer, order, and order-item schema tests."""

from decimal import Decimal

from app.schemas.customer import CustomerDetail, CustomerSummary
from app.schemas.order import OrderDetail, OrderSummary
from app.schemas.order_item import OrderItemDetail, OrderItemSummary


def test_customer_summary_serializes_orm_attributes(graph):
    schema = CustomerSummary.model_validate(graph.customer)

    assert schema.id == graph.customer.id
    assert schema.is_active is True
    assert "orders" not in schema.model_dump()


def test_customer_detail_uses_compact_non_recursive_relationships(graph):
    data = CustomerDetail.model_validate(graph.customer).model_dump()

    assert data["orders"][0]["total_amount"] == Decimal("25.50")
    assert data["conversations"][0]["status"] == "open"
    assert "customer" not in data["orders"][0]
    assert "messages" not in data["conversations"][0]


def test_order_summary_preserves_decimal_and_nullable_datetime(graph):
    schema = OrderSummary.model_validate(graph.order)

    assert schema.total_amount == Decimal("25.50")
    assert isinstance(schema.total_amount, Decimal)
    assert schema.estimated_delivery_time is None


def test_order_detail_serializes_compact_customer_items_and_conversations(graph):
    data = OrderDetail.model_validate(graph.order).model_dump()

    assert data["customer"]["email"] == "sara@example.test"
    assert data["items"][0]["unit_price"] == Decimal("12.75")
    assert data["conversations"][0]["id"] == graph.conversation.id
    assert "orders" not in data["customer"]


def test_order_item_summary_and_detail_match_public_shape(graph):
    summary = OrderItemSummary.model_validate(graph.item)
    detail = OrderItemDetail.model_validate(graph.item)

    assert summary.model_dump() == detail.model_dump()
    assert summary.unit_price == Decimal("12.75")
