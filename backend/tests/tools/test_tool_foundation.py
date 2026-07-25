"""Stage 8.1 discovery tests for enabled metadata and the demo tool."""

import inspect
import json

import pytest
from pydantic import BaseModel, ValidationError

from app.tools import (
    AmbiguousToolLookupError,
    BaseTool,
    DuplicateToolRegistrationError,
    ExecutionContext,
    PingInput,
    PingOutput,
    PingTool,
    ToolCategory,
    ToolMetadata,
    ToolRegistry,
    ToolResult,
)
from app.tools import registry as registry_module


class DemoInput(BaseModel):
    value: str


class DemoOutput(BaseModel):
    value: str


def make_metadata(
    name: str,
    version: str = "1.0.0",
    *,
    enabled: bool = True,
) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        version=version,
        description=f"Demonstration metadata for {name}.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("contract_verification",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
        is_enabled=enabled,
    )


def tool_class(
    name: str,
    version: str = "1.0.0",
    *,
    enabled: bool = True,
) -> type[BaseTool]:
    class DemoTool(BaseTool[DemoInput, DemoOutput]):
        metadata = make_metadata(name, version, enabled=enabled)
        input_schema = DemoInput
        output_schema = DemoOutput

        def execute(
            self,
            context: ExecutionContext,
            input_model: DemoInput,
        ) -> ToolResult[DemoOutput]:
            raise AssertionError("discovery must not execute a tool")

    return DemoTool


def test_ping_tool_exposes_complete_model_neutral_definition() -> None:
    definition = PingTool.definition()

    assert definition["name"] == "ping"
    assert definition["version"] == "1.0.0"
    assert definition["description"]
    assert definition["is_enabled"] is True
    assert definition["input_schema"] == PingInput.model_json_schema()
    assert definition["output_schema"] == PingOutput.model_json_schema()
    json.dumps(definition)


def test_name_only_registration_lookup_and_duplicate_rejection() -> None:
    registry = ToolRegistry()
    registry.register(PingTool)

    assert registry.get("ping") is PingTool
    assert registry.has("ping") is True
    with pytest.raises(DuplicateToolRegistrationError):
        registry.register(PingTool)


def test_name_only_lookup_rejects_ambiguous_versions() -> None:
    registry = ToolRegistry()
    registry.register(tool_class("versioned", "1.0.0"))
    registry.register(tool_class("versioned", "2.0.0"))

    with pytest.raises(AmbiguousToolLookupError, match="specify a version"):
        registry.get("versioned")


def test_all_and_enabled_listings_are_deterministic() -> None:
    alpha = tool_class("alpha")
    disabled = tool_class("disabled", enabled=False)
    registry = ToolRegistry()
    registry.register(PingTool)
    registry.register(disabled)
    registry.register(alpha)

    assert registry.list_all() == (alpha, disabled, PingTool)
    assert registry.list_enabled() == (alpha, PingTool)
    assert registry.list_enabled() == registry.list_enabled()


def test_registry_returns_frozen_metadata_and_filters_it() -> None:
    disabled = tool_class("disabled", enabled=False)
    registry = ToolRegistry()
    registry.register(PingTool)
    registry.register(disabled)

    assert registry.metadata() == (disabled.metadata, PingTool.metadata)
    assert registry.metadata(enabled_only=True) == (PingTool.metadata,)
    with pytest.raises(ValidationError):
        registry.metadata()[0].description = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"description": "   "}, "value must not be empty"),
        ({"version": "version-one"}, "semantic-version format"),
    ],
)
def test_invalid_metadata_fails_fast(
    overrides: dict[str, str], message: str
) -> None:
    values = make_metadata("invalid").model_dump()
    values.update(overrides)

    with pytest.raises(ValidationError, match=message):
        ToolMetadata(**values)


def test_registry_is_provider_independent_and_discovery_only() -> None:
    events = {"instances": 0, "executions": 0}

    class DiscoveryOnlyTool(BaseTool[DemoInput, DemoOutput]):
        metadata = make_metadata("discovery_only")
        input_schema = DemoInput
        output_schema = DemoOutput

        def __init__(self) -> None:
            events["instances"] += 1

        def execute(
            self,
            context: ExecutionContext,
            input_model: DemoInput,
        ) -> ToolResult[DemoOutput]:
            events["executions"] += 1
            raise AssertionError("registry must not execute tools")

    registry = ToolRegistry()
    registry.register(DiscoveryOnlyTool)
    registry.get("discovery_only")
    registry.list_enabled()
    registry.metadata()
    registry.definitions()

    assert events == {"instances": 0, "executions": 0}
    assert "app.providers" not in inspect.getsource(registry_module)
