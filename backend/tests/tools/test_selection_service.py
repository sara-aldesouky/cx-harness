"""Tests for provider-neutral tool-selection orchestration."""

import inspect

import pytest

from app.tools import (
    AmbiguousToolLookupError,
    BaseTool,
    DisabledToolSelectionError,
    ExecutionContext,
    InvalidToolArgumentsError,
    MalformedProviderToolCallError,
    MockProviderToolCallAdapter,
    PingInput,
    PingOutput,
    PingTool,
    ProviderToolCallAdapter,
    ProviderToolCallAdapterNotFoundError,
    ProviderToolCallAdapterRegistry,
    ToolCategory,
    ToolMetadata,
    ToolNotFoundError,
    ToolRegistry,
    ToolResult,
    ToolSelectionAdapterLookupError,
    ToolSelectionRequest,
    ToolSelectionResolutionError,
    ToolSelectionResolver,
    ToolSelectionService,
    ToolSelectionTranslationError,
    ToolSelections,
)
from app.tools import selection_service as service_module


def provider_call(
    call_id: str = "call-001",
    *,
    name: str = "ping",
    version: object = "1.0.0",
    arguments: object = None,
) -> dict[str, object]:
    return {
        "id": call_id,
        "name": name,
        "version": version,
        "arguments": arguments if arguments is not None else {"message": "hello"},
    }


def build_service(
    *,
    tool_registry: ToolRegistry = None,  # type: ignore[assignment]
    adapter: ProviderToolCallAdapter = None,  # type: ignore[assignment]
) -> ToolSelectionService:
    tools = tool_registry or ToolRegistry()
    if not tools.has("ping"):
        tools.register(PingTool)
    adapters = ProviderToolCallAdapterRegistry()
    adapters.register("mock", adapter or MockProviderToolCallAdapter())
    return ToolSelectionService(adapters, ToolSelectionResolver(tools))


def declared_ping(
    *, version: str = "1.0.0", enabled: bool = True
) -> type[BaseTool]:
    class DeclaredPing(BaseTool[PingInput, PingOutput]):
        metadata = ToolMetadata(
            name="ping",
            version=version,
            description="Selection-service test declaration.",
            category=ToolCategory.SYSTEM,
            supported_use_cases=("selection_service_test",),
            requires_customer_identity=False,
            requires_order_ownership=False,
            requires_policy_check=False,
            is_read_only=True,
            is_enabled=enabled,
        )
        input_schema = PingInput
        output_schema = PingOutput

        def execute(
            self,
            context: ExecutionContext,
            input_model: PingInput,
        ) -> ToolResult[PingOutput]:
            raise AssertionError("selection service must not execute tools")

    return DeclaredPing


def test_no_tool_calls_returns_empty_tuple() -> None:
    assert build_service().select("mock", {"tool_calls": []}) == ()


def test_one_valid_selection_is_translated_and_resolved() -> None:
    result = build_service().select(
        "mock", {"tool_calls": [provider_call()]}
    )

    assert len(result) == 1
    assert result[0].call_id == "call-001"
    assert result[0].tool_name == "ping"
    assert result[0].tool_version == "1.0.0"
    assert result[0].arguments == {"message": "hello"}


def test_multiple_selections_preserve_provider_order() -> None:
    result = build_service().select(
        "mock",
        {
            "tool_calls": [
                provider_call("call-003", arguments={"message": "third"}),
                provider_call("call-001", arguments={"message": "first"}),
                provider_call("call-002", arguments={"message": "second"}),
            ]
        },
    )

    assert tuple(item.call_id for item in result) == (
        "call-003",
        "call-001",
        "call-002",
    )


def test_provider_normalization_is_delegated_to_adapter_registry() -> None:
    result = build_service().select(
        "  MoCk  ", {"tool_calls": [provider_call()]}
    )

    assert result[0].tool_name == "ping"


def test_explicit_and_safe_name_only_versions_resolve() -> None:
    service = build_service()
    explicit = service.select("mock", {"tool_calls": [provider_call()]})
    name_only_call = provider_call()
    del name_only_call["version"]
    name_only = service.select("mock", {"tool_calls": [name_only_call]})

    assert explicit[0].tool_version == "1.0.0"
    assert name_only[0].tool_version == "1.0.0"


def test_arguments_are_normalized_by_selected_input_schema() -> None:
    result = build_service().select(
        "mock",
        {"tool_calls": [provider_call(arguments={"message": " hello "})]},
    )

    assert result[0].arguments == {"message": "hello"}


def test_unknown_provider_is_wrapped_with_lookup_boundary() -> None:
    with pytest.raises(ToolSelectionAdapterLookupError) as captured:
        build_service().select("unknown", {"tool_calls": []})

    assert isinstance(captured.value.__cause__, ProviderToolCallAdapterNotFoundError)
    assert "unknown" in str(captured.value)


def test_malformed_provider_output_is_wrapped_with_translation_boundary() -> None:
    with pytest.raises(ToolSelectionTranslationError) as captured:
        build_service().select("mock", {"tool_calls": "private payload"})

    assert isinstance(captured.value.__cause__, MalformedProviderToolCallError)
    assert "private payload" not in str(captured.value)


@pytest.mark.parametrize(
    ("tool_registry", "call", "cause_type"),
    [
        (ToolRegistry(), provider_call(name="missing"), ToolNotFoundError),
        (
            (lambda registry: (
                registry.register(declared_ping(enabled=False)) or registry
            ))(ToolRegistry()),
            provider_call(),
            DisabledToolSelectionError,
        ),
        (
            (lambda registry: (
                registry.register(declared_ping(version="1.0.0")),
                registry.register(declared_ping(version="2.0.0")),
                registry,
            )[-1])(ToolRegistry()),
            {key: value for key, value in provider_call().items() if key != "version"},
            AmbiguousToolLookupError,
        ),
        (
            ToolRegistry(),
            provider_call(arguments={"message": "   "}),
            InvalidToolArgumentsError,
        ),
    ],
)
def test_resolution_failures_have_safe_index_and_call_context(
    tool_registry: ToolRegistry,
    call: dict[str, object],
    cause_type: type[Exception],
) -> None:
    if cause_type in (ToolNotFoundError, InvalidToolArgumentsError):
        tool_registry.register(PingTool)

    with pytest.raises(ToolSelectionResolutionError) as captured:
        build_service(tool_registry=tool_registry).select(
            "mock", {"tool_calls": [call]}
        )

    assert isinstance(captured.value.__cause__, cause_type)
    assert "index 0" in str(captured.value)
    assert "call-001" in str(captured.value)
    assert "message" not in str(captured.value)


def test_fail_fast_stops_before_processing_later_calls() -> None:
    class TrackingResolver(ToolSelectionResolver):
        def __init__(self, registry: ToolRegistry) -> None:
            super().__init__(registry)
            self.call_ids: list[str] = []

        def resolve(self, request: ToolSelectionRequest):  # type: ignore[no-untyped-def]
            self.call_ids.append(request.call_id)
            return super().resolve(request)

    tools = ToolRegistry()
    tools.register(PingTool)
    resolver = TrackingResolver(tools)
    adapters = ProviderToolCallAdapterRegistry()
    adapters.register("mock", MockProviderToolCallAdapter())
    service = ToolSelectionService(adapters, resolver)

    with pytest.raises(ToolSelectionResolutionError):
        service.select(
            "mock",
            {
                "tool_calls": [
                    provider_call("call-001"),
                    provider_call("call-002", name="missing"),
                    provider_call("call-003"),
                ]
            },
        )

    assert resolver.call_ids == ["call-001", "call-002"]


def test_returned_collection_and_nested_selections_are_immutable() -> None:
    result = build_service().select(
        "mock", {"tool_calls": [provider_call()]}
    )

    assert isinstance(result, tuple)
    with pytest.raises(TypeError):
        result[0] = result[0]  # type: ignore[index]
    with pytest.raises(TypeError):
        result[0].arguments["message"] = "changed"  # type: ignore[index]


def test_service_construction_does_not_translate() -> None:
    class TrackingAdapter(ProviderToolCallAdapter):
        def __init__(self) -> None:
            self.calls = 0

        def translate(self, provider_output: object) -> ToolSelections:
            self.calls += 1
            return ()

    adapter = TrackingAdapter()
    build_service(adapter=adapter)

    assert adapter.calls == 0


def test_service_never_instantiates_or_executes_tools() -> None:
    events = {"instances": 0, "executions": 0}

    class NeverRunPing(BaseTool[PingInput, PingOutput]):
        metadata = ToolMetadata(
            name="ping",
            version="1.0.0",
            description="Prove orchestration is validation-only.",
            category=ToolCategory.SYSTEM,
            supported_use_cases=("selection_service_test",),
            requires_customer_identity=False,
            requires_order_ownership=False,
            requires_policy_check=False,
            is_read_only=True,
            is_enabled=True,
        )
        input_schema = PingInput
        output_schema = PingOutput

        def __init__(self) -> None:
            events["instances"] += 1

        def execute(
            self,
            context: ExecutionContext,
            input_model: PingInput,
        ) -> ToolResult[PingOutput]:
            events["executions"] += 1
            raise AssertionError("selection service must not execute tools")

    tools = ToolRegistry()
    tools.register(NeverRunPing)
    build_service(tool_registry=tools).select(
        "mock", {"tool_calls": [provider_call()]}
    )

    assert events == {"instances": 0, "executions": 0}


def test_constructor_rejects_invalid_dependencies() -> None:
    tools = ToolRegistry()
    resolver = ToolSelectionResolver(tools)
    adapters = ProviderToolCallAdapterRegistry()

    with pytest.raises(TypeError, match="adapter_registry"):
        ToolSelectionService(object(), resolver)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="selection_resolver"):
        ToolSelectionService(adapters, object())  # type: ignore[arg-type]


def test_service_has_no_runtime_database_http_or_provider_dependencies() -> None:
    source = inspect.getsource(service_module).lower()

    for forbidden in (
        "sqlalchemy",
        "fastapi",
        "httpx",
        "import requests",
        "app.providers",
        "modelrun",
        "promptmanager",
        "toolexecutor",
        ".execute(",
    ):
        assert forbidden not in source
