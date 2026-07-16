"""Tool-call and evaluation response-schema tests."""

from decimal import Decimal

from app.schemas.evaluation import EvaluationDetail, EvaluationSummary
from app.schemas.tool_call import ToolCallDetail, ToolCallSummary


def test_tool_call_summary_excludes_payloads(graph):
    data = ToolCallSummary.model_validate(graph.tool_call).model_dump()

    assert data["latency_ms"] == 25
    assert "input_json" not in data
    assert "output_json" not in data
    assert "error_message" not in data


def test_tool_call_detail_preserves_json_and_nullables(graph):
    schema = ToolCallDetail.model_validate(graph.tool_call)

    assert schema.input_json == {"order_id": "TEST-001"}
    assert schema.output_json == {"status": "pending"}
    assert schema.error_message is None
    assert schema.started_at is None


def test_evaluation_summary_preserves_decimal(graph):
    schema = EvaluationSummary.model_validate(graph.evaluation)

    assert schema.overall_score == Decimal("4.25")
    assert isinstance(schema.overall_score, Decimal)
    assert "details_json" not in schema.model_dump()


def test_evaluation_detail_preserves_partial_scores_and_json(graph):
    schema = EvaluationDetail.model_validate(graph.evaluation)

    assert schema.tone_score is None
    assert schema.tool_score == Decimal("4.50")
    assert schema.details_json == {"expected_intent": "order_status"}
