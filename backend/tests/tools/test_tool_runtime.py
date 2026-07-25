"""Tests for the tool-continuation application composition root."""

import inspect
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.tools import (
    ExecutionContext,
    InvalidToolContinuationRuntimeDependencyError,
    MockProviderContinuationAdapter,
    PingTool,
    ProviderContinuationAdapterRegistry,
    SingleToolContinuationCycleService,
    ToolContinuationCycle,
    ToolContinuationRuntime,
    ToolContinuationRuntimeConstructionError,
    ToolRegistry,
    ToolSelectionRequest,
    ToolSelectionResolver,
    build_tool_continuation_runtime,
)
from app.tools import tool_runtime as runtime_module
from tests.tools.audit_fakes import RecordingAuditRepository


def dependencies():  # type: ignore[no-untyped-def]
    tools = ToolRegistry()
    continuations = ProviderContinuationAdapterRegistry()
    audit = RecordingAuditRepository()
    return tools, continuations, audit


def test_successful_composition_returns_immutable_runtime_and_service() -> None:
    tools, continuations, audit = dependencies()

    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
    )

    assert isinstance(runtime, ToolContinuationRuntime)
    assert isinstance(runtime.cycle_service, SingleToolContinuationCycleService)
    with pytest.raises(FrozenInstanceError):
        runtime.cycle_service = runtime.cycle_service  # type: ignore[misc]


def test_external_dependency_instances_are_preserved_through_graph() -> None:
    tools, continuations, audit = dependencies()
    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
        audit_payload_max_bytes=2048,
    )

    service = runtime.cycle_service
    gateway = service._execution_gateway

    assert gateway._registry is tools
    assert gateway._executor._registry is tools
    assert gateway._executor._audit_repository is audit
    assert gateway._executor._audit_payload_max_bytes == 2048
    assert service._continuation_service._adapter_registry is continuations


class FalseyAuditRepository(RecordingAuditRepository):
    def __bool__(self) -> bool:
        return False


def test_falsey_but_valid_audit_dependency_is_not_replaced() -> None:
    tools = ToolRegistry()
    continuations = ProviderContinuationAdapterRegistry()
    audit = FalseyAuditRepository()

    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
    )

    assert runtime.cycle_service._execution_gateway._executor._audit_repository is audit


def test_each_build_creates_independent_graph_with_deliberately_shared_inputs() -> None:
    tools, continuations, audit = dependencies()

    first = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
    )
    second = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
    )

    assert first is not second
    assert first.cycle_service is not second.cycle_service
    assert first.cycle_service._execution_gateway is not second.cycle_service._execution_gateway
    assert first.cycle_service._execution_gateway._registry is tools
    assert second.cycle_service._execution_gateway._registry is tools
    assert first.cycle_service._continuation_service._adapter_registry is continuations
    assert second.cycle_service._continuation_service._adapter_registry is continuations


def test_builder_does_not_register_resolve_execute_translate_or_write_audit() -> None:
    class TrackingToolRegistry(ToolRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.lookups = 0

        def get(self, name: str, version: str = None):  # type: ignore[no-untyped-def,override]
            self.lookups += 1
            return super().get(name, version)

    class TrackingContinuationRegistry(ProviderContinuationAdapterRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.lookups = 0

        def get(self, provider_name: str):  # type: ignore[no-untyped-def]
            self.lookups += 1
            return super().get(provider_name)

    tools = TrackingToolRegistry()
    continuations = TrackingContinuationRegistry()
    audit = RecordingAuditRepository()

    build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
    )

    assert tools.list() == ()
    assert continuations.list_providers() == ()
    assert tools.lookups == continuations.lookups == 0
    assert audit.started == audit.finalized == []


def test_real_explicitly_populated_runtime_produces_completed_ping_cycle() -> None:
    tools, continuations, audit = dependencies()
    tools.register(PingTool)
    continuations.register("mock", MockProviderContinuationAdapter())
    selected = ToolSelectionResolver(tools).resolve(
        ToolSelectionRequest(
            call_id="call-001",
            tool_name="ping",
            arguments={"message": "hello"},
        )
    )
    runtime = build_tool_continuation_runtime(
        tool_registry=tools,
        continuation_adapter_registry=continuations,
        audit_repository=audit,
    )

    cycle = runtime.cycle_service.run(
        "mock",
        selected,
        ExecutionContext(trace_id=uuid4(), execution_id=uuid4()),
    )

    assert isinstance(cycle, ToolContinuationCycle)
    assert cycle.selection is selected
    assert cycle.continuation_payload.payload["output"] == {"pong": "pong"}
    assert len(audit.started) == len(audit.finalized) == 1


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("tool_registry", object(), "tool_registry"),
        ("continuation_adapter_registry", object(), "continuation_adapter_registry"),
        ("audit_repository", object(), "audit_repository"),
        ("audit_repository", None, "audit_repository"),
        ("audit_payload_max_bytes", 0, "audit_payload_max_bytes"),
        ("audit_payload_max_bytes", -1, "audit_payload_max_bytes"),
        ("audit_payload_max_bytes", True, "audit_payload_max_bytes"),
    ],
)
def test_invalid_external_dependencies_fail_before_construction(
    field: str, invalid: object, message: str
) -> None:
    tools, continuations, audit = dependencies()
    values = {
        "tool_registry": tools,
        "continuation_adapter_registry": continuations,
        "audit_repository": audit,
        "audit_payload_max_bytes": 16_384,
    }
    values[field] = invalid

    with pytest.raises(InvalidToolContinuationRuntimeDependencyError, match=message):
        build_tool_continuation_runtime(**values)  # type: ignore[arg-type]

    assert audit.started == audit.finalized == []


def test_missing_required_dependency_is_rejected_by_public_signature() -> None:
    tools, continuations, _ = dependencies()

    with pytest.raises(TypeError, match="audit_repository"):
        build_tool_continuation_runtime(  # type: ignore[call-arg]
            tool_registry=tools,
            continuation_adapter_registry=continuations,
        )


@pytest.mark.parametrize(
    ("target", "stage"),
    [
        ("ToolExecutor", "tool_executor"),
        ("SingleToolExecutionGateway", "execution_gateway"),
        ("ProviderContinuationService", "continuation_service"),
        ("SingleToolContinuationCycleService", "cycle_service"),
    ],
)
def test_internal_construction_failure_is_safe_and_preserves_cause(
    monkeypatch: pytest.MonkeyPatch, target: str, stage: str
) -> None:
    tools, continuations, audit = dependencies()
    original = RuntimeError("private object repr and secret")

    def fail(*args: object, **kwargs: object) -> None:
        raise original

    monkeypatch.setattr(runtime_module, target, fail)

    with pytest.raises(ToolContinuationRuntimeConstructionError) as captured:
        build_tool_continuation_runtime(
            tool_registry=tools,
            continuation_adapter_registry=continuations,
            audit_repository=audit,
        )

    assert captured.value.__cause__ is original
    assert stage in str(captured.value)
    assert "secret" not in str(captured.value)
    assert audit.started == audit.finalized == []


def test_composition_has_no_environment_database_network_fastapi_or_runtime_cache() -> None:
    source = inspect.getsource(runtime_module).lower()

    for forbidden in (
        "get_session_factory",
        "create_engine",
        "database_url",
        "os.environ",
        "getenv",
        "settings",
        "sqlalchemy",
        "fastapi",
        "httpx",
        "requests",
        "lru_cache",
        "@cache",
        ".register(",
        ".get(",
        ".execute(",
        ".translate(",
        ".run(",
    ):
        assert forbidden not in source
