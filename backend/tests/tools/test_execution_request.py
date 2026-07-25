"""Unit tests for the trusted tool-execution request boundary."""

import inspect
import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.tools import (
    ExecutionContext,
    InvalidExecutionContextError,
    InvalidExecutionRequestInputError,
    PingTool,
    ToolExecutionRequest,
    ToolExecutionRequestFactory,
    ToolRegistry,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ValidatedToolSelection,
)
from app.tools import execution_request as request_module


def validated_selection(
    *, arguments: object = None
) -> ValidatedToolSelection:
    registry = ToolRegistry()
    registry.register(PingTool)
    request = ToolSelectionRequest(
        call_id="call-001",
        tool_name="ping",
        arguments=arguments if arguments is not None else {"message": " hello "},
    )
    return ToolSelectionResolver(registry).resolve(request)


def trusted_context(**overrides: object) -> ExecutionContext:
    values = {
        "trace_id": uuid4(),
        "execution_id": uuid4(),
        "conversation_id": uuid4(),
        "model_run_id": uuid4(),
        "customer_id": uuid4(),
        "model_name": "qwen3:8b",
        "experiment_id": "experiment-001",
        "use_case_id": "tool-selection",
    }
    values.update(overrides)
    return ExecutionContext(**values)


def test_valid_request_is_built_from_selection_and_context() -> None:
    selection = validated_selection()
    context = trusted_context()

    request = ToolExecutionRequestFactory().create(selection, context)

    assert request.call_id == "call-001"
    assert request.tool_name == "ping"
    assert request.tool_version == "1.0.0"
    assert request.arguments == {"message": "hello"}
    assert request.context == context
    assert request.context is not context


def test_optional_context_fields_remain_optional() -> None:
    context = ExecutionContext(trace_id=uuid4(), execution_id=uuid4())

    request = ToolExecutionRequestFactory().create(
        validated_selection(), context
    )

    assert request.context.conversation_id is None
    assert request.context.customer_id is None
    assert request.context.model_run_id is None
    assert request.context.model_name is None


def test_arguments_are_defensively_copied_and_deeply_immutable() -> None:
    source = {"message": "hello", "nested": {"items": ["one"]}}
    selection = ValidatedToolSelection(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        arguments=source,
    )
    request = ToolExecutionRequestFactory().create(selection, trusted_context())
    source["nested"]["items"].append("changed")  # type: ignore[index,union-attr]

    assert request.arguments["nested"]["items"] == ("one",)
    assert request.arguments is not selection.arguments
    with pytest.raises(TypeError):
        request.arguments["message"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        request.arguments["nested"]["items"] += ("changed",)  # type: ignore[index,operator]


def test_request_and_copied_context_are_immutable() -> None:
    request = ToolExecutionRequestFactory().create(
        validated_selection(), trusted_context()
    )

    with pytest.raises(ValidationError, match="frozen"):
        request.call_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        request.context.customer_id = uuid4()  # type: ignore[misc]


def test_factory_rejects_raw_provider_or_selection_payloads() -> None:
    with pytest.raises(
        InvalidExecutionRequestInputError,
        match="ValidatedToolSelection",
    ):
        ToolExecutionRequestFactory().create(  # type: ignore[arg-type]
            {
                "id": "call-001",
                "name": "ping",
                "arguments": {"message": "secret"},
            },
            trusted_context(),
        )


@pytest.mark.parametrize("invalid", [None, {}, object()])
def test_factory_rejects_invalid_context_objects(invalid: object) -> None:
    with pytest.raises(
        InvalidExecutionContextError,
        match="trusted ExecutionContext",
    ):
        ToolExecutionRequestFactory().create(  # type: ignore[arg-type]
            validated_selection(), invalid
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_name", ""),
        ("experiment_id", "   "),
        ("use_case_id", ""),
        ("trace_id", "not-a-uuid"),
        ("execution_id", ""),
    ],
)
def test_trusted_context_rejects_blank_labels_and_malformed_uuids(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        trusted_context(**{field: value})


def test_trusted_context_rejects_arbitrary_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExecutionContext(
            trace_id=uuid4(),
            execution_id=uuid4(),
            authorization={"role": "invented"},
        )


def test_factory_does_not_revalidate_tool_input_schema() -> None:
    selection = ValidatedToolSelection(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        arguments={"already_validated_marker": 42},
    )

    request = ToolExecutionRequestFactory().create(selection, trusted_context())

    assert request.arguments == {"already_validated_marker": 42}


def test_serialization_is_deterministic_and_json_compatible() -> None:
    request = ToolExecutionRequestFactory().create(
        validated_selection(), trusted_context()
    )

    first = request.model_dump(mode="json")
    second = request.model_dump(mode="json")

    assert first == second
    assert request.model_dump_json() == request.model_dump_json()
    assert json.loads(request.model_dump_json()) == first
    assert UUID(first["context"]["trace_id"]) == request.context.trace_id
    assert "provider_output" not in first
    assert "registry" not in first


@pytest.mark.parametrize("field", ["call_id", "tool_name", "tool_version"])
def test_execution_request_contract_rejects_blank_identifiers(field: str) -> None:
    values = {
        "call_id": "call-001",
        "tool_name": "ping",
        "tool_version": "1.0.0",
        "arguments": {"message": "hello"},
        "context": trusted_context(),
    }
    values[field] = "   "

    with pytest.raises(ValidationError, match="must not be empty"):
        ToolExecutionRequest(**values)


def test_execution_request_contract_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ToolExecutionRequest(
            call_id="call-001",
            tool_name="ping",
            tool_version="1.0.0",
            arguments={"message": "hello"},
            context=trusted_context(),
            raw_provider_output={"secret": True},
        )


def test_boundary_has_no_registry_execution_repository_or_runtime_dependencies() -> None:
    source = inspect.getsource(request_module).lower()

    for forbidden in (
        "toolregistry",
        "input_schema",
        "basetool",
        "toolexecutor",
        ".execute(",
        "from app.database",
        "import app.database",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "app.providers",
    ):
        assert forbidden not in source
