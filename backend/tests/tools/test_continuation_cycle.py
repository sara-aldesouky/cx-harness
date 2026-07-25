"""Tests for the immutable completed tool-continuation cycle contract."""

import inspect
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tools import (
    ExecutionContext,
    InvalidToolContinuationCycleInputError,
    MockProviderContinuationAdapter,
    MockProviderToolCallAdapter,
    PingTool,
    ProviderContinuationAdapterRegistry,
    ProviderContinuationPayload,
    ProviderContinuationService,
    ProviderToolCallAdapterRegistry,
    SingleToolExecutionGateway,
    ToolContinuationCycle,
    ToolContinuationCycleArtifactMismatchError,
    ToolContinuationCycleCorrelationError,
    ToolContinuationCycleFactory,
    ToolContinuationCycleIdentityMismatchError,
    ToolContinuationCycleProviderMismatchError,
    ToolError,
    ToolExecutionOutcome,
    ToolExecutionOutcomeFactory,
    ToolExecutionRequest,
    ToolExecutionRequestFactory,
    ToolExecutor,
    ToolRegistry,
    ToolSelectionResolver,
    ToolSelectionService,
    ToolStatus,
    ValidatedToolSelection,
)
from app.tools import continuation_cycle as cycle_module
from tests.tools.audit_fakes import RecordingAuditRepository


def completed_cycle_artifacts():  # type: ignore[no-untyped-def]
    tools = ToolRegistry()
    tools.register(PingTool)
    provider_adapters = ProviderToolCallAdapterRegistry()
    provider_adapters.register("mock", MockProviderToolCallAdapter())
    selection = ToolSelectionService(
        provider_adapters, ToolSelectionResolver(tools)
    ).select(
        "mock",
        {
            "tool_calls": [
                {
                    "id": "Call-001",
                    "name": "ping",
                    "version": "1.0.0",
                    "arguments": {"message": " hello "},
                }
            ]
        },
    )[0]
    request = ToolExecutionRequestFactory().create(
        selection,
        ExecutionContext(trace_id=uuid4(), execution_id=uuid4()),
    )
    audit = RecordingAuditRepository()
    result = SingleToolExecutionGateway(
        tools, ToolExecutor(tools, audit)
    ).execute(request)
    outcome = ToolExecutionOutcomeFactory().create(request, result)
    continuation_adapters = ProviderContinuationAdapterRegistry()
    continuation_adapters.register("mock", MockProviderContinuationAdapter())
    payload = ProviderContinuationService(continuation_adapters).translate(
        "mock", outcome
    )
    return selection, request, outcome, payload, audit


def create_cycle(
    *,
    provider_name: object = "mock",
    selection: object = None,
    request: object = None,
    outcome: object = None,
    payload: object = None,
) -> ToolContinuationCycle:
    defaults = completed_cycle_artifacts()
    return ToolContinuationCycleFactory().create(
        provider_name=provider_name,  # type: ignore[arg-type]
        selection=defaults[0] if selection is None else selection,  # type: ignore[arg-type]
        execution_request=defaults[1] if request is None else request,  # type: ignore[arg-type]
        execution_outcome=defaults[2] if outcome is None else outcome,  # type: ignore[arg-type]
        continuation_payload=defaults[3] if payload is None else payload,  # type: ignore[arg-type]
    )


def test_real_in_process_lifecycle_creates_completed_success_cycle() -> None:
    selection, request, outcome, payload, audit = completed_cycle_artifacts()

    cycle = ToolContinuationCycleFactory().create(
        "mock", selection, request, outcome, payload
    )

    assert cycle.provider_name == "mock"
    assert cycle.selection.call_id == "Call-001"
    assert cycle.execution_outcome.status is ToolStatus.SUCCESS
    assert cycle.continuation_payload.payload["status"] == "success"
    assert len(audit.started) == len(audit.finalized) == 1


def test_completed_business_failure_cycle_is_valid() -> None:
    selection, request, _, _, _ = completed_cycle_artifacts()
    outcome = ToolExecutionOutcome(
        call_id=request.call_id,
        tool_name=request.tool_name,
        tool_version=request.tool_version,
        status=ToolStatus.FAILURE,
        error=ToolError(
            error_code="PING_FAILED",
            public_message="The ping request could not be completed.",
        ),
    )
    adapters = ProviderContinuationAdapterRegistry()
    adapters.register("mock", MockProviderContinuationAdapter())
    payload = ProviderContinuationService(adapters).translate("mock", outcome)

    cycle = ToolContinuationCycleFactory().create(
        "mock", selection, request, outcome, payload
    )

    assert cycle.execution_outcome.status is ToolStatus.FAILURE
    assert cycle.continuation_payload.payload["status"] == "failure"


def test_provider_name_is_normalized() -> None:
    assert create_cycle(provider_name="  MoCk  ").provider_name == "mock"


def test_original_nested_contract_instances_are_preserved() -> None:
    selection, request, outcome, payload, _ = completed_cycle_artifacts()

    cycle = ToolContinuationCycleFactory().create(
        "mock", selection, request, outcome, payload
    )

    assert cycle.selection is selection
    assert cycle.execution_request is request
    assert cycle.execution_outcome is outcome
    assert cycle.continuation_payload is payload


@pytest.mark.parametrize("artifact", ["request", "outcome", "payload"])
def test_each_call_id_mismatch_is_rejected(artifact: str) -> None:
    selection, request, outcome, payload, _ = completed_cycle_artifacts()
    values = {
        "selection": selection,
        "request": request,
        "outcome": outcome,
        "payload": payload,
    }
    values[artifact] = values[artifact].model_copy(update={"call_id": "call-999"})

    with pytest.raises(ToolContinuationCycleCorrelationError):
        ToolContinuationCycleFactory().create(
            "mock",
            values["selection"],
            values["request"],
            values["outcome"],
            values["payload"],
        )


@pytest.mark.parametrize("artifact", ["request", "outcome"])
def test_tool_name_mismatch_is_rejected(artifact: str) -> None:
    selection, request, outcome, payload, _ = completed_cycle_artifacts()
    values = {"request": request, "outcome": outcome}
    values[artifact] = values[artifact].model_copy(update={"tool_name": "other"})

    with pytest.raises(ToolContinuationCycleIdentityMismatchError, match="names"):
        ToolContinuationCycleFactory().create(
            "mock", selection, values["request"], values["outcome"], payload
        )


@pytest.mark.parametrize("artifact", ["request", "outcome"])
def test_tool_version_mismatch_is_rejected(artifact: str) -> None:
    selection, request, outcome, payload, _ = completed_cycle_artifacts()
    values = {"request": request, "outcome": outcome}
    values[artifact] = values[artifact].model_copy(update={"tool_version": "2.0.0"})

    with pytest.raises(ToolContinuationCycleIdentityMismatchError, match="versions"):
        ToolContinuationCycleFactory().create(
            "mock", selection, values["request"], values["outcome"], payload
        )


def test_equivalent_immutable_arguments_are_consistent() -> None:
    cycle = create_cycle()

    assert cycle.selection.arguments == cycle.execution_request.arguments
    assert cycle.selection.arguments == {"message": "hello"}


def test_selection_request_argument_mismatch_is_rejected_without_values_in_error() -> None:
    selection, request, outcome, payload, _ = completed_cycle_artifacts()
    wrong_request = request.model_copy(update={"arguments": {"message": "private"}})

    with pytest.raises(ToolContinuationCycleArtifactMismatchError) as captured:
        ToolContinuationCycleFactory().create(
            "mock", selection, wrong_request, outcome, payload
        )

    assert "private" not in str(captured.value)


def test_provider_payload_identity_mismatch_is_rejected() -> None:
    selection, request, outcome, payload, _ = completed_cycle_artifacts()
    wrong_payload = payload.model_copy(update={"provider_name": "gemini"})

    with pytest.raises(ToolContinuationCycleProviderMismatchError):
        ToolContinuationCycleFactory().create(
            "mock", selection, request, outcome, wrong_payload
        )


def test_provider_specific_payload_internals_are_not_parsed() -> None:
    selection, request, outcome, _, _ = completed_cycle_artifacts()
    opaque = ProviderContinuationPayload(
        provider_name="mock",
        call_id=outcome.call_id,
        payload={"opaque_provider_shape": {"unrelated_tool": "ignored"}},
    )

    cycle = ToolContinuationCycleFactory().create(
        "mock", selection, request, outcome, opaque
    )

    assert cycle.continuation_payload is opaque


def test_success_serialization_is_deterministic_and_lifecycle_ordered() -> None:
    cycle = create_cycle()

    first = cycle.model_dump(mode="json")
    second = cycle.model_dump(mode="json")

    assert first == second
    assert list(first) == [
        "provider_name",
        "selection",
        "execution_request",
        "execution_outcome",
        "continuation_payload",
    ]
    assert json.loads(cycle.model_dump_json()) == first
    assert cycle.model_dump_json() == cycle.model_dump_json()


def test_failure_cycle_serializes_safely() -> None:
    selection, request, _, _, _ = completed_cycle_artifacts()
    outcome = ToolExecutionOutcome(
        call_id=request.call_id,
        tool_name=request.tool_name,
        tool_version=request.tool_version,
        status=ToolStatus.FAILURE,
        error=ToolError(error_code="SAFE", public_message="Unable to complete."),
    )
    adapters = ProviderContinuationAdapterRegistry()
    adapters.register("mock", MockProviderContinuationAdapter())
    payload = ProviderContinuationService(adapters).translate("mock", outcome)
    cycle = ToolContinuationCycleFactory().create(
        "mock", selection, request, outcome, payload
    )

    serialized = cycle.model_dump(mode="json")

    assert serialized["execution_outcome"]["status"] == "failure"
    assert serialized["continuation_payload"]["payload"]["status"] == "failure"


def test_cycle_and_nested_artifacts_are_immutable() -> None:
    cycle = create_cycle()

    with pytest.raises(ValidationError, match="frozen"):
        cycle.provider_name = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        cycle.selection = cycle.selection  # type: ignore[misc]
    with pytest.raises(TypeError):
        cycle.execution_request.arguments["message"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        cycle.continuation_payload.payload["status"] = "changed"  # type: ignore[index]


def test_mutating_caller_data_cannot_change_cycle() -> None:
    arguments = {"message": "hello"}
    selection = ValidatedToolSelection(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        arguments=arguments,
    )
    arguments["message"] = "changed"
    request = ToolExecutionRequest(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        arguments={"message": "hello"},
        context=ExecutionContext(trace_id=uuid4(), execution_id=uuid4()),
    )
    outcome = ToolExecutionOutcome(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        status=ToolStatus.SUCCESS,
        output={"pong": "pong"},
    )
    payload_source = {"type": "tool_result"}
    payload = ProviderContinuationPayload(
        provider_name="mock", call_id="call-001", payload=payload_source
    )
    payload_source["type"] = "changed"

    cycle = ToolContinuationCycleFactory().create(
        "mock", selection, request, outcome, payload
    )

    assert cycle.selection.arguments == {"message": "hello"}
    assert cycle.continuation_payload.payload == {"type": "tool_result"}


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("selection", {}),
        ("request", {}),
        ("outcome", {}),
        ("payload", {}),
        ("selection", None),
        ("request", None),
        ("outcome", None),
        ("payload", None),
    ],
)
def test_invalid_and_partial_artifacts_are_rejected(field: str, invalid: object) -> None:
    selection, request, outcome, payload, _ = completed_cycle_artifacts()
    values = {
        "selection": selection,
        "request": request,
        "outcome": outcome,
        "payload": payload,
    }
    values[field] = invalid

    with pytest.raises(InvalidToolContinuationCycleInputError):
        ToolContinuationCycleFactory().create(
            "mock",
            values["selection"],
            values["request"],
            values["outcome"],
            values["payload"],
        )


@pytest.mark.parametrize("invalid", ["", "   ", None, 42])
def test_blank_or_invalid_provider_identity_is_rejected(invalid: object) -> None:
    with pytest.raises(InvalidToolContinuationCycleInputError):
        create_cycle(provider_name=invalid)


def test_factory_has_no_registry_execution_translation_runtime_or_io_dependencies() -> None:
    source = inspect.getsource(cycle_module).lower()

    for forbidden in (
        "toolregistry",
        "adapterregistry",
        "continuationservice",
        "toolexecutor",
        ".execute(",
        ".translate(",
        "modelprovider",
        "app.providers",
        "prompt",
        "audit",
        "repository",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "requests",
    ):
        assert forbidden not in source
