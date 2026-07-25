"""Tests for provider continuation translation contracts."""

import inspect
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.tools import (
    ExecutionContext,
    InvalidProviderContinuationOutcomeError,
    MockProviderContinuationAdapter,
    PingTool,
    ProviderContinuationAdapter,
    ProviderContinuationPayload,
    ProviderContinuationSerializationError,
    SingleToolExecutionGateway,
    ToolError,
    ToolExecutionOutcome,
    ToolExecutionOutcomeFactory,
    ToolExecutionRequestFactory,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ToolStatus,
    UnsupportedProviderContinuationStateError,
)
from app.tools import continuation_adapter as adapter_module
from tests.tools.audit_fakes import RecordingAuditRepository


def request_and_success_outcome():  # type: ignore[no-untyped-def]
    registry = ToolRegistry()
    registry.register(PingTool)
    selection = ToolSelectionResolver(registry).resolve(
        ToolSelectionRequest(
            call_id="Call-001",
            tool_name="ping",
            arguments={"message": "hello"},
        )
    )
    request = ToolExecutionRequestFactory().create(
        selection,
        ExecutionContext(trace_id=uuid4(), execution_id=uuid4()),
    )
    audit = RecordingAuditRepository()
    result = SingleToolExecutionGateway(
        registry, ToolExecutor(registry, audit)
    ).execute(request)
    outcome = ToolExecutionOutcomeFactory().create(request, result)
    return request, outcome, audit


def failure_outcome() -> ToolExecutionOutcome:
    return ToolExecutionOutcome(
        call_id="call-002",
        tool_name="ping",
        tool_version="1.0.0",
        status=ToolStatus.FAILURE,
        error=ToolError(
            error_code="PING_FAILED",
            public_message="The ping request could not be completed.",
        ),
    )


def test_adapter_interface_is_abstract() -> None:
    with pytest.raises(TypeError):
        ProviderContinuationAdapter()


def test_real_ping_outcome_translates_to_mock_success_protocol() -> None:
    _, outcome, audit = request_and_success_outcome()

    continuation = MockProviderContinuationAdapter().translate(outcome)

    assert continuation.provider_name == "mock"
    assert continuation.call_id == "Call-001"
    assert continuation.payload == {
        "type": "tool_result",
        "call_id": "Call-001",
        "tool": {"name": "ping", "version": "1.0.0"},
        "status": "success",
        "output": {"pong": "pong"},
    }
    assert "error" not in continuation.payload
    assert len(audit.started) == len(audit.finalized) == 1


def test_business_failure_translates_to_safe_mock_failure_protocol() -> None:
    continuation = MockProviderContinuationAdapter().translate(failure_outcome())

    assert continuation.call_id == "call-002"
    assert continuation.payload == {
        "type": "tool_result",
        "call_id": "call-002",
        "tool": {"name": "ping", "version": "1.0.0"},
        "status": "failure",
        "error": {
            "code": "PING_FAILED",
            "message": "The ping request could not be completed.",
        },
    }
    assert "output" not in continuation.payload


def test_identity_and_status_are_preserved_without_conversational_prose() -> None:
    _, outcome, _ = request_and_success_outcome()

    continuation = MockProviderContinuationAdapter().translate(outcome)

    assert continuation.payload["call_id"] == outcome.call_id
    assert continuation.payload["tool"]["name"] == outcome.tool_name
    assert continuation.payload["tool"]["version"] == outcome.tool_version
    assert continuation.payload["status"] == outcome.status.value
    assert set(continuation.payload) == {
        "type",
        "call_id",
        "tool",
        "status",
        "output",
    }


def test_payload_is_defensively_copied_and_deeply_immutable() -> None:
    source = {
        "type": "tool_result",
        "nested": {"items": ["one"]},
    }
    continuation = ProviderContinuationPayload(
        provider_name=" MOCK ", call_id=" Call-001 ", payload=source
    )
    source["nested"]["items"].append("changed")  # type: ignore[index,union-attr]

    assert continuation.provider_name == "mock"
    assert continuation.call_id == "Call-001"
    assert continuation.payload["nested"]["items"] == ("one",)
    with pytest.raises(TypeError):
        continuation.payload["type"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        continuation.payload["nested"]["items"] += ("changed",)  # type: ignore[index,operator]
    with pytest.raises(ValidationError, match="frozen"):
        continuation.call_id = "changed"  # type: ignore[misc]


def test_serialization_is_deterministic_and_json_compatible() -> None:
    _, outcome, _ = request_and_success_outcome()
    continuation = MockProviderContinuationAdapter().translate(outcome)

    first = continuation.model_dump(mode="json")
    second = continuation.model_dump(mode="json")

    assert first == second
    assert continuation.model_dump_json() == continuation.model_dump_json()
    assert json.loads(continuation.model_dump_json()) == first


@pytest.mark.parametrize("invalid", [{}, object(), "outcome"])
def test_invalid_outcome_objects_are_rejected(invalid: object) -> None:
    with pytest.raises(InvalidProviderContinuationOutcomeError):
        MockProviderContinuationAdapter().translate(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "outcome",
    [
        ToolExecutionOutcome.model_construct(
            call_id="call-001",
            tool_name="ping",
            tool_version="1.0.0",
            status="unknown",
            output=None,
            error=None,
        ),
        ToolExecutionOutcome.model_construct(
            call_id="call-001",
            tool_name="ping",
            tool_version="1.0.0",
            status=ToolStatus.SUCCESS,
            output=None,
            error=None,
        ),
        ToolExecutionOutcome.model_construct(
            call_id="call-001",
            tool_name="ping",
            tool_version="1.0.0",
            status=ToolStatus.FAILURE,
            output={"pong": "invalid"},
            error=None,
        ),
    ],
)
def test_unsupported_or_malformed_outcome_state_is_rejected(
    outcome: ToolExecutionOutcome,
) -> None:
    with pytest.raises(UnsupportedProviderContinuationStateError):
        MockProviderContinuationAdapter().translate(outcome)


def test_non_serializable_continuation_data_is_wrapped_safely() -> None:
    outcome = ToolExecutionOutcome.model_construct(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        status=ToolStatus.SUCCESS,
        output={"private": object()},
        error=None,
    )

    with pytest.raises(ProviderContinuationSerializationError) as captured:
        MockProviderContinuationAdapter().translate(outcome)

    assert "object at" not in str(captured.value)


@pytest.mark.parametrize(
    "values",
    [
        {"provider_name": "", "call_id": "call", "payload": {"type": "x"}},
        {"provider_name": "mock", "call_id": " ", "payload": {"type": "x"}},
        {"provider_name": "mock", "call_id": "call", "payload": {}},
        {
            "provider_name": "mock",
            "call_id": "call",
            "payload": {"bad": object()},
        },
    ],
)
def test_direct_payload_contract_rejects_invalid_data(
    values: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        ProviderContinuationPayload(**values)


def test_direct_payload_contract_forbids_unexpected_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProviderContinuationPayload(
            provider_name="mock",
            call_id="call-001",
            payload={"type": "tool_result"},
            raw_provider_response={"secret": True},
        )


def test_translation_does_not_execute_tools_or_write_duplicate_audits() -> None:
    _, outcome, audit = request_and_success_outcome()
    before = (len(audit.started), len(audit.finalized))
    adapter = MockProviderContinuationAdapter()

    adapter.translate(outcome)
    adapter.translate(outcome)

    assert before == (1, 1)
    assert (len(audit.started), len(audit.finalized)) == before


def test_adapter_has_no_model_registry_prompt_database_or_network_dependencies() -> None:
    source = inspect.getsource(adapter_module).lower()

    for forbidden in (
        "toolexecutor",
        ".execute(",
        "toolregistry",
        "modelprovider",
        "app.providers",
        "promptmanager",
        "fastapi",
        "sqlalchemy",
        "httpx",
        "from app.database",
    ):
        assert forbidden not in source
