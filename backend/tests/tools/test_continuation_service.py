"""Tests for provider-neutral continuation translation orchestration."""

import inspect
from typing import Any
from uuid import uuid4

import pytest

from app.tools import (
    ExecutionContext,
    InvalidProviderContinuationAdapterNameError,
    InvalidProviderContinuationPayloadError,
    MockProviderContinuationAdapter,
    PingTool,
    ProviderContinuationAdapter,
    ProviderContinuationAdapterLookupError,
    ProviderContinuationAdapterNotFoundError,
    ProviderContinuationAdapterRegistry,
    ProviderContinuationAdapterError,
    ProviderContinuationPayload,
    ProviderContinuationPayloadMismatchError,
    ProviderContinuationService,
    ProviderContinuationTranslationError,
    SingleToolExecutionGateway,
    ToolError,
    ToolExecutionOutcome,
    ToolExecutionOutcomeFactory,
    ToolExecutionRequestFactory,
    ToolExecutor,
    ToolRegistry,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ToolStatus,
)
from app.tools import continuation_service as service_module
from tests.tools.audit_fakes import RecordingAuditRepository


def success_outcome() -> tuple[ToolExecutionOutcome, RecordingAuditRepository]:
    tools = ToolRegistry()
    tools.register(PingTool)
    selection = ToolSelectionResolver(tools).resolve(
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
        tools, ToolExecutor(tools, audit)
    ).execute(request)
    return ToolExecutionOutcomeFactory().create(request, result), audit


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


def build_service(
    adapter: ProviderContinuationAdapter = None,  # type: ignore[assignment]
) -> ProviderContinuationService:
    registry = ProviderContinuationAdapterRegistry()
    registry.register("mock", adapter or MockProviderContinuationAdapter())
    return ProviderContinuationService(registry)


class TrackingAdapter(ProviderContinuationAdapter):
    def __init__(self, payload: Any = None, error: Exception = None) -> None:  # type: ignore[assignment]
        self.payload = payload
        self.error = error
        self.calls = 0
        self.outcomes: list[ToolExecutionOutcome] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    def translate(
        self, outcome: ToolExecutionOutcome
    ) -> ProviderContinuationPayload:
        self.calls += 1
        self.outcomes.append(outcome)
        if self.error is not None:
            raise self.error
        return self.payload  # type: ignore[no-any-return]


def test_real_ping_flow_translates_through_service_once() -> None:
    outcome, audit = success_outcome()
    service = build_service()

    payload = service.translate("mock", outcome)

    assert payload.provider_name == "mock"
    assert payload.call_id == "Call-001"
    assert payload.payload["status"] == "success"
    assert payload.payload["output"] == {"pong": "pong"}
    assert len(audit.started) == len(audit.finalized) == 1


def test_provider_lookup_normalizes_case_and_whitespace() -> None:
    outcome, _ = success_outcome()

    payload = build_service().translate("  MoCk  ", outcome)

    assert payload.provider_name == "mock"


def test_adapter_receives_original_outcome_once_and_payload_instance_is_preserved() -> None:
    outcome, _ = success_outcome()
    expected = ProviderContinuationPayload(
        provider_name="mock",
        call_id=outcome.call_id,
        payload={"type": "tool_result", "status": "success"},
    )
    adapter = TrackingAdapter(expected)

    actual = build_service(adapter).translate("mock", outcome)

    assert adapter.calls == 1
    assert adapter.outcomes == [outcome]
    assert adapter.outcomes[0] is outcome
    assert actual is expected


def test_business_failure_is_translated_without_becoming_an_exception() -> None:
    outcome = failure_outcome()

    payload = build_service().translate("mock", outcome)

    assert payload.call_id == outcome.call_id
    assert payload.payload["status"] == "failure"
    assert payload.payload["error"]["code"] == "PING_FAILED"


def test_unknown_provider_error_is_wrapped_with_cause() -> None:
    outcome, _ = success_outcome()

    with pytest.raises(ProviderContinuationAdapterLookupError) as unknown:
        build_service().translate("unknown", outcome)
    assert isinstance(unknown.value.__cause__, ProviderContinuationAdapterNotFoundError)


@pytest.mark.parametrize("provider_name", [" ", None, 42])
def test_invalid_provider_errors_are_wrapped_with_causes(
    provider_name: object,
) -> None:
    outcome, _ = success_outcome()

    with pytest.raises(ProviderContinuationAdapterLookupError) as invalid:
        build_service().translate(provider_name, outcome)  # type: ignore[arg-type]
    assert isinstance(
        invalid.value.__cause__, InvalidProviderContinuationAdapterNameError
    )


def test_adapter_domain_failure_is_wrapped_and_cause_preserved() -> None:
    outcome, _ = success_outcome()
    original = ProviderContinuationAdapterError("private adapter failure")
    adapter = TrackingAdapter(error=original)

    with pytest.raises(ProviderContinuationTranslationError) as captured:
        build_service(adapter).translate("mock", outcome)

    assert captured.value.__cause__ is original
    assert "private adapter failure" not in str(captured.value)
    assert adapter.calls == 1


@pytest.mark.parametrize("invalid", [None, {}, object()])
def test_non_contract_adapter_results_are_rejected(invalid: object) -> None:
    outcome, _ = success_outcome()

    with pytest.raises(InvalidProviderContinuationPayloadError):
        build_service(TrackingAdapter(invalid)).translate("mock", outcome)


def test_returned_provider_mismatch_is_rejected_without_repair() -> None:
    outcome, _ = success_outcome()
    wrong = ProviderContinuationPayload(
        provider_name="gemini",
        call_id=outcome.call_id,
        payload={"type": "tool_result"},
    )

    with pytest.raises(ProviderContinuationPayloadMismatchError, match="provider"):
        build_service(TrackingAdapter(wrong)).translate("mock", outcome)

    assert wrong.provider_name == "gemini"


def test_returned_call_id_mismatch_is_rejected_without_repair() -> None:
    outcome, _ = success_outcome()
    wrong = ProviderContinuationPayload(
        provider_name="mock",
        call_id="call-999",
        payload={"type": "tool_result"},
    )

    with pytest.raises(ProviderContinuationPayloadMismatchError, match="call ID"):
        build_service(TrackingAdapter(wrong)).translate("mock", outcome)

    assert wrong.call_id == "call-999"


def test_valid_identity_and_deep_immutability_are_preserved() -> None:
    outcome, _ = success_outcome()
    expected = ProviderContinuationPayload(
        provider_name="mock",
        call_id=outcome.call_id,
        payload={"nested": {"items": ["one"]}},
    )

    actual = build_service(TrackingAdapter(expected)).translate("mock", outcome)

    assert actual is expected
    assert actual.call_id == outcome.call_id
    with pytest.raises(TypeError):
        actual.payload["nested"]["items"] += ("two",)  # type: ignore[index,operator]


def test_invalid_outcome_and_batch_inputs_are_rejected_before_lookup() -> None:
    class LookupTrackingRegistry(ProviderContinuationAdapterRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.lookups = 0

        def get(self, provider_name: str) -> ProviderContinuationAdapter:
            self.lookups += 1
            return super().get(provider_name)

    registry = LookupTrackingRegistry()
    registry.register("mock", MockProviderContinuationAdapter())
    service = ProviderContinuationService(registry)

    for invalid in (None, {}, [failure_outcome()], (failure_outcome(),)):
        with pytest.raises(ProviderContinuationTranslationError):
            service.translate("mock", invalid)  # type: ignore[arg-type]

    assert registry.lookups == 0


def test_constructor_validates_dependency_without_lookup_or_translation() -> None:
    with pytest.raises(TypeError, match="adapter_registry"):
        ProviderContinuationService(object())  # type: ignore[arg-type]

    class TrackingRegistry(ProviderContinuationAdapterRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.lookups = 0

        def get(self, provider_name: str) -> ProviderContinuationAdapter:
            self.lookups += 1
            return super().get(provider_name)

    registry = TrackingRegistry()
    adapter = TrackingAdapter()
    registry.register("mock", adapter)

    ProviderContinuationService(registry)

    assert registry.lookups == 0
    assert adapter.calls == 0


def test_service_has_no_execution_provider_prompt_audit_database_or_network_dependencies() -> None:
    source = inspect.getsource(service_module).lower()

    for forbidden in (
        "toolregistry",
        "toolexecutor",
        ".execute(",
        "modelprovider",
        "app.providers",
        "promptmanager",
        "modelrun",
        "audit",
        "repository",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "requests",
    ):
        assert forbidden not in source
