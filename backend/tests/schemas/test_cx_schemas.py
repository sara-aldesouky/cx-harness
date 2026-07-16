"""Conversation, message, and model-run schema tests."""

from decimal import Decimal

from app.schemas.conversation import ConversationDetail, ConversationSummary
from app.schemas.message import MessageSummary
from app.schemas.model_run import ModelRunDetail, ModelRunSummary


def test_message_serialization_handles_nullable_language(graph):
    schema = MessageSummary.model_validate(graph.message)

    assert schema.language is None
    assert schema.content == "Where is my order?"
    assert "conversation" not in schema.model_dump()


def test_conversation_summary_handles_nullable_fields(graph):
    schema = ConversationSummary.model_validate(graph.conversation)

    assert schema.ended_at is None
    assert schema.related_order_id == graph.order.id


def test_conversation_detail_stops_at_model_run_summaries(graph):
    data = ConversationDetail.model_validate(graph.conversation).model_dump()

    assert data["customer"]["id"] == graph.customer.id
    assert data["related_order"]["order_number"] == "TEST-001"
    assert data["messages"][0]["sequence_number"] == 1
    assert data["model_runs"][0]["estimated_cost"] == Decimal("0.001000")
    assert "tool_calls" not in data["model_runs"][0]
    assert "evaluations" not in data["model_runs"][0]


def test_model_run_summary_preserves_decimal_and_nullable_values(graph):
    schema = ModelRunSummary.model_validate(graph.model_run)

    assert schema.estimated_cost == Decimal("0.001000")
    assert schema.temperature == Decimal("0.50")
    assert schema.finished_at is None


def test_model_run_detail_expands_only_tool_calls_and_evaluations(graph):
    data = ModelRunDetail.model_validate(graph.model_run).model_dump()

    assert data["tool_calls"][0]["tool_name"] == "get_order_status"
    assert data["evaluations"][0]["overall_score"] == Decimal("4.25")
    assert "input_json" not in data["tool_calls"][0]
    assert "details_json" not in data["evaluations"][0]
    assert "conversation" not in data
