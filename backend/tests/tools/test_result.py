"""Unit tests for standard business-tool results."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from app.tools import ToolError, ToolResult, ToolStatus


class ExampleOutput(BaseModel):
    order_status: str


def test_valid_success_result_uses_typed_output():
    result = ToolResult[ExampleOutput](
        status=ToolStatus.SUCCESS,
        data={"order_status": "preparing"},
    )

    assert result.status is ToolStatus.SUCCESS
    assert isinstance(result.data, ExampleOutput)
    assert result.data.order_status == "preparing"
    assert result.error is None


def test_success_serialization_is_deterministic_and_json_compatible():
    result = ToolResult[ExampleOutput](
        status="success",
        data=ExampleOutput(order_status="delivered"),
    )

    first = result.model_dump(mode="json")
    second = result.model_dump(mode="json")

    assert first == second
    assert first == {
        "status": "success",
        "data": {"order_status": "delivered"},
        "error": None,
    }
    assert json.loads(json.dumps(first)) == first
    assert json.loads(result.model_dump_json()) == first


def test_valid_failure_result_contains_only_safe_error():
    result = ToolResult[ExampleOutput](
        status=ToolStatus.FAILURE,
        error=ToolError(
            error_code="  ORDER_NOT_FOUND  ",
            public_message="  The requested order was not found.  ",
        ),
    )

    assert result.status is ToolStatus.FAILURE
    assert result.data is None
    assert result.error.error_code == "ORDER_NOT_FOUND"
    assert result.error.public_message == "The requested order was not found."
    assert result.model_dump(mode="json") == {
        "status": "failure",
        "data": None,
        "error": {
            "error_code": "ORDER_NOT_FOUND",
            "public_message": "The requested order was not found.",
        },
    }


def test_success_without_data_is_rejected():
    with pytest.raises(ValidationError, match="successful tool results require data"):
        ToolResult[ExampleOutput](status=ToolStatus.SUCCESS)


def test_success_with_error_is_rejected():
    with pytest.raises(ValidationError, match="must not include an error"):
        ToolResult[ExampleOutput](
            status=ToolStatus.SUCCESS,
            data=ExampleOutput(order_status="delivered"),
            error=ToolError(
                error_code="UNEXPECTED",
                public_message="An unexpected result was returned.",
            ),
        )


def test_failure_with_data_is_rejected():
    with pytest.raises(ValidationError, match="must not include data"):
        ToolResult[ExampleOutput](
            status=ToolStatus.FAILURE,
            data=ExampleOutput(order_status="unknown"),
            error=ToolError(
                error_code="ORDER_NOT_FOUND",
                public_message="The requested order was not found.",
            ),
        )


def test_failure_without_error_is_rejected():
    with pytest.raises(ValidationError, match="failed tool results require an error"):
        ToolResult[ExampleOutput](status=ToolStatus.FAILURE)


@pytest.mark.parametrize("field", ["error_code", "public_message"])
@pytest.mark.parametrize("value", ["", "   "])
def test_tool_error_rejects_empty_safe_text(field, value):
    values = {
        "error_code": "ORDER_NOT_FOUND",
        "public_message": "The requested order was not found.",
    }
    values[field] = value

    with pytest.raises(ValidationError, match="empty or whitespace"):
        ToolError(**values)


@pytest.mark.parametrize("field", ["status", "data", "error"])
def test_tool_result_is_immutable(field):
    result = ToolResult[ExampleOutput](
        status=ToolStatus.SUCCESS,
        data=ExampleOutput(order_status="delivered"),
    )

    with pytest.raises(ValidationError, match="frozen"):
        setattr(result, field, None)


def test_tool_error_is_immutable():
    error = ToolError(
        error_code="ORDER_NOT_FOUND",
        public_message="The requested order was not found.",
    )

    with pytest.raises(ValidationError, match="frozen"):
        error.error_code = "CHANGED"  # type: ignore[misc]


def test_failure_json_serialization_is_deterministic():
    result = ToolResult[ExampleOutput](
        status=ToolStatus.FAILURE,
        error=ToolError(
            error_code="PAYMENT_ALREADY_REFUNDED",
            public_message="This payment has already been refunded.",
        ),
    )

    assert result.model_dump_json() == result.model_dump_json()
    assert json.loads(result.model_dump_json())["status"] == "failure"
