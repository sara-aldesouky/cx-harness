"""Unit tests for trusted tool-execution context."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tools import ExecutionContext


def valid_context(**overrides: object) -> ExecutionContext:
    values = {
        "trace_id": uuid4(),
        "execution_id": uuid4(),
        "conversation_id": uuid4(),
        "model_run_id": uuid4(),
        "customer_id": uuid4(),
        "model_name": "gemini-2.0-flash",
        "experiment_id": "experiment-001",
        "use_case_id": "order-status",
    }
    values.update(overrides)
    return ExecutionContext(**values)


def test_valid_execution_context_is_normalized():
    context = valid_context(
        model_name="  gemini-2.0-flash  ",
        experiment_id="  experiment-001  ",
        use_case_id="  order-status  ",
    )

    assert context.model_name == "gemini-2.0-flash"
    assert context.experiment_id == "experiment-001"
    assert context.use_case_id == "order-status"


def test_context_supports_only_required_correlation_ids():
    context = ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        model_name=None,
        experiment_id=None,
        use_case_id=None,
    )

    assert context.customer_id is None
    assert context.conversation_id is None
    assert context.model_run_id is None
    assert context.model_name is None
    assert context.experiment_id is None
    assert context.use_case_id is None


def test_uuid_values_serialize_as_strings():
    context = valid_context()
    serialized = context.model_dump(mode="json")

    assert serialized["trace_id"] == str(context.trace_id)
    assert serialized["execution_id"] == str(context.execution_id)
    assert serialized["conversation_id"] == str(context.conversation_id)
    assert serialized["model_run_id"] == str(context.model_run_id)
    assert serialized["customer_id"] == str(context.customer_id)


@pytest.mark.parametrize("field", ["customer_id", "trace_id"])
def test_trusted_identity_is_immutable(field):
    context = valid_context()

    with pytest.raises(ValidationError, match="frozen"):
        setattr(context, field, uuid4())


@pytest.mark.parametrize("field", ["model_name", "experiment_id", "use_case_id"])
@pytest.mark.parametrize("value", ["", "   "])
def test_context_rejects_empty_optional_labels(field, value):
    with pytest.raises(ValidationError, match="empty or whitespace"):
        valid_context(**{field: value})


def test_serialization_is_deterministic_and_json_serializable():
    context = valid_context()

    first = context.model_dump(mode="json")
    second = context.model_dump(mode="json")

    assert first == second
    assert json.loads(json.dumps(first)) == first
    assert context.model_dump_json() == context.model_dump_json()


def test_context_schema_intentionally_excludes_tool_arguments():
    fields = ExecutionContext.model_fields

    assert "order_id" not in fields
    assert "input_json" not in fields
    assert "tool_name" not in fields


def test_context_rejects_tool_arguments_as_extra_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExecutionContext(
            trace_id=uuid4(),
            execution_id=uuid4(),
            order_id="ORDER-12345",
        )
