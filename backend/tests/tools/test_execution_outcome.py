"""Tests for provider-neutral correlated tool execution outcomes."""

import inspect
import json
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.tools import (
    ExecutionContext,
    InvalidToolExecutionOutcomeRequestError,
    InvalidToolExecutionOutcomeResultError,
    NonSerializableToolOutputError,
    PingOutput,
    PingTool,
    SingleToolExecutionGateway,
    ToolError,
    ToolExecutionOutcome,
    ToolExecutionOutcomeFactory,
    ToolExecutionOutcomeIdentityMismatchError,
    ToolExecutionRequest,
    ToolExecutionRequestFactory,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ToolStatus,
    UnsupportedToolResultStateError,
)
from app.tools import execution_outcome as outcome_module
from tests.tools.audit_fakes import RecordingAuditRepository


def execution_context() -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        conversation_id=uuid4(),
        customer_id=uuid4(),
    )


def execution_request() -> ToolExecutionRequest:
    registry = ToolRegistry()
    registry.register(PingTool)
    selection = ToolSelectionResolver(registry).resolve(
        ToolSelectionRequest(
            call_id="call-001",
            tool_name="ping",
            arguments={"message": "hello"},
        )
    )
    return ToolExecutionRequestFactory().create(selection, execution_context())


def test_real_ping_path_produces_correlated_success_outcome() -> None:
    registry = ToolRegistry()
    registry.register(PingTool)
    audit = RecordingAuditRepository()
    gateway = SingleToolExecutionGateway(
        registry, ToolExecutor(registry, audit)
    )
    request = execution_request()

    result = gateway.execute(request)
    outcome = ToolExecutionOutcomeFactory().create(request, result)

    assert outcome == ToolExecutionOutcome(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        status=ToolStatus.SUCCESS,
        output={"pong": "pong"},
        error=None,
    )
    assert len(audit.started) == len(audit.finalized) == 1


def test_factory_preserves_request_identity_and_existing_status() -> None:
    request = execution_request()
    result = ToolResult[PingOutput](
        status=ToolStatus.SUCCESS,
        data=PingOutput(pong="pong"),
    )

    outcome = ToolExecutionOutcomeFactory().create(request, result)

    assert outcome.call_id == request.call_id
    assert outcome.tool_name == request.tool_name
    assert outcome.tool_version == request.tool_version
    assert outcome.status is result.status


def test_business_failure_preserves_only_safe_structured_error() -> None:
    result = ToolResult[PingOutput](
        status=ToolStatus.FAILURE,
        error=ToolError(
            error_code="PING_REJECTED",
            public_message="The ping request was rejected.",
        ),
    )

    outcome = ToolExecutionOutcomeFactory().create(execution_request(), result)

    assert outcome.status is ToolStatus.FAILURE
    assert outcome.output is None
    assert outcome.error == result.error
    assert outcome.error is not result.error
    assert outcome.model_dump(mode="json")["error"] == {
        "error_code": "PING_REJECTED",
        "public_message": "The ping request was rejected.",
    }


def test_output_is_defensively_copied_and_deeply_immutable() -> None:
    class NestedOutput(BaseModel):
        labels: list[str]
        details: dict[str, list[int]]

    data = NestedOutput(labels=["one"], details={"values": [1, 2]})
    result = ToolResult[NestedOutput](status=ToolStatus.SUCCESS, data=data)
    outcome = ToolExecutionOutcomeFactory().create(execution_request(), result)
    data.labels.append("changed")
    data.details["values"].append(3)

    assert outcome.output == {
        "labels": ("one",),
        "details": {"values": (1, 2)},
    }
    with pytest.raises(TypeError):
        outcome.output["labels"] = ("changed",)  # type: ignore[index]
    with pytest.raises(TypeError):
        outcome.output["details"]["values"] += (3,)  # type: ignore[index,operator]


def test_outcome_and_error_are_immutable() -> None:
    outcome = ToolExecutionOutcomeFactory().create(
        execution_request(),
        ToolResult[PingOutput](
            status=ToolStatus.FAILURE,
            error=ToolError(error_code="NO_PING", public_message="No ping."),
        ),
    )

    with pytest.raises(ValidationError, match="frozen"):
        outcome.status = ToolStatus.SUCCESS  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        outcome.error.error_code = "CHANGED"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["call_id", "tool_name", "tool_version"])
def test_outcome_rejects_blank_identity(field: str) -> None:
    values = {
        "call_id": "call-001",
        "tool_name": "ping",
        "tool_version": "1.0.0",
        "status": ToolStatus.SUCCESS,
        "output": {"pong": "pong"},
    }
    values[field] = "   "

    with pytest.raises(ValidationError, match="must not be empty"):
        ToolExecutionOutcome(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"status": ToolStatus.SUCCESS, "output": None, "error": None},
        {
            "status": ToolStatus.SUCCESS,
            "output": {"pong": "pong"},
            "error": ToolError(error_code="ERROR", public_message="Error."),
        },
        {
            "status": ToolStatus.FAILURE,
            "output": {"pong": "pong"},
            "error": ToolError(error_code="ERROR", public_message="Error."),
        },
        {"status": ToolStatus.FAILURE, "output": None, "error": None},
    ],
)
def test_outcome_contract_rejects_inconsistent_status_payloads(
    values: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        ToolExecutionOutcome(
            call_id="call-001",
            tool_name="ping",
            tool_version="1.0.0",
            **values,
        )


def test_serialization_is_deterministic_and_provider_neutral() -> None:
    outcome = ToolExecutionOutcomeFactory().create(
        execution_request(),
        ToolResult[PingOutput](
            status=ToolStatus.SUCCESS,
            data=PingOutput(pong="pong"),
        ),
    )

    first = outcome.model_dump(mode="json")
    second = outcome.model_dump(mode="json")

    assert first == second
    assert outcome.model_dump_json() == outcome.model_dump_json()
    assert json.loads(outcome.model_dump_json()) == first
    assert set(first) == {
        "call_id",
        "tool_name",
        "tool_version",
        "status",
        "output",
        "error",
    }


class IdentifiedPingResult(ToolResult[PingOutput]):
    tool_name: str
    tool_version: str


def test_matching_optional_result_identity_is_accepted() -> None:
    result = IdentifiedPingResult(
        status=ToolStatus.SUCCESS,
        data=PingOutput(pong="pong"),
        tool_name="ping",
        tool_version="1.0.0",
    )

    outcome = ToolExecutionOutcomeFactory().create(execution_request(), result)

    assert outcome.tool_name == "ping"
    assert outcome.tool_version == "1.0.0"


@pytest.mark.parametrize(
    ("name", "version", "message"),
    [
        ("order_lookup", "1.0.0", "name does not match"),
        ("ping", "2.0.0", "version does not match"),
    ],
)
def test_optional_result_identity_mismatch_is_rejected(
    name: str, version: str, message: str
) -> None:
    result = IdentifiedPingResult(
        status=ToolStatus.SUCCESS,
        data=PingOutput(pong="pong"),
        tool_name=name,
        tool_version=version,
    )

    with pytest.raises(ToolExecutionOutcomeIdentityMismatchError, match=message):
        ToolExecutionOutcomeFactory().create(execution_request(), result)


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        ToolSelectionRequest(
            call_id="call-001",
            tool_name="ping",
            arguments={"message": "hello"},
        ),
        object(),
    ],
)
def test_invalid_request_input_is_rejected(invalid: object) -> None:
    result = ToolResult[PingOutput](
        status=ToolStatus.SUCCESS, data=PingOutput(pong="pong")
    )

    with pytest.raises(InvalidToolExecutionOutcomeRequestError):
        ToolExecutionOutcomeFactory().create(  # type: ignore[arg-type]
            invalid, result
        )


@pytest.mark.parametrize("invalid", [{}, PingOutput(pong="pong"), object()])
def test_invalid_result_input_is_rejected(invalid: object) -> None:
    with pytest.raises(InvalidToolExecutionOutcomeResultError):
        ToolExecutionOutcomeFactory().create(  # type: ignore[arg-type]
            execution_request(), invalid
        )


@pytest.mark.parametrize(
    "malformed",
    [
        ToolResult.model_construct(status="unknown", data=None, error=None),
        ToolResult.model_construct(
            status=ToolStatus.SUCCESS, data=None, error=None
        ),
        ToolResult.model_construct(
            status=ToolStatus.FAILURE,
            data=PingOutput(pong="invalid"),
            error=None,
        ),
    ],
)
def test_malformed_or_unsupported_result_state_is_rejected(
    malformed: ToolResult,
) -> None:
    with pytest.raises(UnsupportedToolResultStateError):
        ToolExecutionOutcomeFactory().create(execution_request(), malformed)


def test_non_serializable_output_is_rejected_without_exposing_value() -> None:
    class NonSerializableOutput(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)

        value: object

    result = ToolResult[NonSerializableOutput](
        status=ToolStatus.SUCCESS,
        data=NonSerializableOutput(value=object()),
    )

    with pytest.raises(NonSerializableToolOutputError) as captured:
        ToolExecutionOutcomeFactory().create(execution_request(), result)

    assert "object at" not in str(captured.value)


def test_outcome_factory_does_not_reexecute_or_duplicate_audit() -> None:
    registry = ToolRegistry()
    registry.register(PingTool)
    audit = RecordingAuditRepository()
    gateway = SingleToolExecutionGateway(
        registry, ToolExecutor(registry, audit)
    )
    request = execution_request()
    result = gateway.execute(request)
    counts_before = (len(audit.started), len(audit.finalized))

    factory = ToolExecutionOutcomeFactory()
    factory.create(request, result)
    factory.create(request, result)

    assert counts_before == (1, 1)
    assert (len(audit.started), len(audit.finalized)) == counts_before


def test_outcome_module_has_no_execution_provider_http_or_database_dependencies() -> None:
    source = inspect.getsource(outcome_module).lower()

    for forbidden in (
        "toolexecutor",
        "singletoolexecutiongateway",
        ".execute(",
        "app.providers",
        "fastapi",
        "sqlalchemy",
        "from app.database",
        "prompt",
    ):
        assert forbidden not in source
