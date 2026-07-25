"""Unit tests for provider-neutral tool-selection contracts."""

import inspect
import json

import pytest
from pydantic import ValidationError

from app.tools import (
    AmbiguousToolLookupError,
    BaseTool,
    DisabledToolSelectionError,
    ExecutionContext,
    InvalidToolArgumentsError,
    InvalidToolSelectionRequestError,
    PingInput,
    PingOutput,
    PingTool,
    ToolCategory,
    ToolMetadata,
    ToolNotFoundError,
    ToolRegistry,
    ToolResult,
    ToolSelectionRequest,
    ToolSelectionResolver,
    ValidatedToolSelection,
)
from app.tools import selection as selection_module


def selection(
    **overrides: object,
) -> ToolSelectionRequest:
    values = {
        "call_id": "call-001",
        "tool_name": "ping",
        "tool_version": "1.0.0",
        "arguments": {"message": "hello"},
    }
    values.update(overrides)
    return ToolSelectionRequest(**values)


def registry_with_ping() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(PingTool)
    return registry


def declared_ping(
    *, name: str = "ping", version: str = "1.0.0", enabled: bool = True
) -> type[BaseTool]:
    class DeclaredPing(BaseTool[PingInput, PingOutput]):
        metadata = ToolMetadata(
            name=name,
            version=version,
            description="Validate selection behavior without execution.",
            category=ToolCategory.SYSTEM,
            supported_use_cases=("selection_verification",),
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
            raise AssertionError("selection resolution must not execute tools")

    return DeclaredPing


def test_explicit_selection_resolves_and_normalizes_arguments() -> None:
    resolved = ToolSelectionResolver(registry_with_ping()).resolve(
        selection(call_id=" call-001 ", arguments={"message": " hello "})
    )

    assert resolved == ValidatedToolSelection(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        arguments={"message": "hello"},
    )


def test_safe_name_only_selection_resolves_the_only_version() -> None:
    resolved = ToolSelectionResolver(registry_with_ping()).resolve(
        selection(tool_version=None)
    )

    assert resolved.tool_version == "1.0.0"
    assert resolved.call_id == "call-001"


def test_unknown_tool_reuses_registry_lookup_error() -> None:
    with pytest.raises(ToolNotFoundError, match="not registered"):
        ToolSelectionResolver(ToolRegistry()).resolve(selection())


def test_disabled_tool_is_rejected() -> None:
    registry = ToolRegistry()
    registry.register(declared_ping(enabled=False))

    with pytest.raises(DisabledToolSelectionError, match="is disabled"):
        ToolSelectionResolver(registry).resolve(selection())


def test_ambiguous_name_only_selection_reuses_registry_error() -> None:
    registry = ToolRegistry()
    registry.register(declared_ping(version="1.0.0"))
    registry.register(declared_ping(version="2.0.0"))

    with pytest.raises(AmbiguousToolLookupError, match="specify a version"):
        ToolSelectionResolver(registry).resolve(selection(tool_version=None))


@pytest.mark.parametrize(
    "arguments",
    [
        {"message": 12},
        {"message": "hello", "unexpected": True},
        {"unexpected": True},
        {"message": "   "},
    ],
)
def test_invalid_arguments_are_hidden_behind_domain_error(arguments: object) -> None:
    with pytest.raises(
        InvalidToolArgumentsError,
        match="arguments for tool 'ping' are invalid",
    ) as captured:
        ToolSelectionResolver(registry_with_ping()).resolve(
            selection(arguments=arguments)
        )

    assert "pydantic" not in str(captured.value).lower()
    assert "validation error" not in str(captured.value).lower()


@pytest.mark.parametrize(
    "overrides",
    [
        {"call_id": "   "},
        {"tool_name": ""},
        {"tool_version": "   "},
        {"arguments": {}},
    ],
)
def test_invalid_selection_request_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        selection(**overrides)


def test_resolver_rejects_objects_outside_request_contract() -> None:
    with pytest.raises(InvalidToolSelectionRequestError):
        ToolSelectionResolver(registry_with_ping()).resolve(  # type: ignore[arg-type]
            {"tool_name": "ping"}
        )


def test_request_and_validated_selection_are_deeply_immutable() -> None:
    source = {"message": "hello", "nested": {"items": ["one"]}}
    request = ToolSelectionRequest(
        call_id="call-001", tool_name="ping", arguments=source
    )
    source["nested"]["items"].append("two")  # type: ignore[index,union-attr]

    assert request.arguments["nested"]["items"] == ("one",)
    with pytest.raises(TypeError):
        request.arguments["message"] = "changed"  # type: ignore[index]
    with pytest.raises(ValidationError):
        request.call_id = "changed"  # type: ignore[misc]


def test_contracts_serialize_deterministically_as_json() -> None:
    request = selection(arguments={"message": "hello", "labels": ["a", "b"]})
    validated = ValidatedToolSelection(
        call_id="call-001",
        tool_name="ping",
        tool_version="1.0.0",
        arguments={"message": "hello"},
    )

    assert request.model_dump_json() == request.model_dump_json()
    assert validated.model_dump_json() == validated.model_dump_json()
    assert json.loads(request.model_dump_json())["arguments"]["labels"] == [
        "a",
        "b",
    ]


def test_resolution_never_instantiates_or_executes_and_preserves_metadata() -> None:
    events = {"instantiated": 0, "executed": 0}

    class DiscoveryOnlyPing(BaseTool[PingInput, PingOutput]):
        metadata = ToolMetadata(
            name="discovery_ping",
            version="1.0.0",
            description="A declaration used to prove resolution is read-only.",
            category=ToolCategory.SYSTEM,
            supported_use_cases=("selection_verification",),
            requires_customer_identity=False,
            requires_order_ownership=False,
            requires_policy_check=False,
            is_read_only=True,
            is_enabled=True,
        )
        input_schema = PingInput
        output_schema = PingOutput

        def __init__(self) -> None:
            events["instantiated"] += 1

        def execute(
            self,
            context: ExecutionContext,
            input_model: PingInput,
        ) -> ToolResult[PingOutput]:
            events["executed"] += 1
            raise AssertionError("resolver must not execute tools")

    registry = ToolRegistry()
    registry.register(DiscoveryOnlyPing)
    metadata_before = registry.metadata()
    ToolSelectionResolver(registry).resolve(
        selection(tool_name="discovery_ping")
    )

    assert events == {"instantiated": 0, "executed": 0}
    assert registry.metadata() == metadata_before


def test_selection_module_is_provider_and_runtime_independent() -> None:
    source = inspect.getsource(selection_module)

    for forbidden in (
        "app.providers",
        "sqlalchemy",
        "fastapi",
        "ollama",
        "qwen",
        "gemini",
        "openai",
    ):
        assert forbidden not in source.lower()
