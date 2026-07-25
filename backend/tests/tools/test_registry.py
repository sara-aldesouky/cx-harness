"""Unit tests for the read-only in-memory tool registry."""

import json

import pytest
from pydantic import BaseModel

from app.tools import (
    BaseTool,
    DuplicateToolRegistrationError,
    ToolCategory,
    ToolMetadata,
    ToolNotFoundError,
    ToolRegistry,
)


class ExampleInput(BaseModel):
    order_id: str


class ExampleOutput(BaseModel):
    status: str


def metadata(name: str, version: str) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        version=version,
        description=f"Definition for {name}",
        category=ToolCategory.ORDER,
        supported_use_cases=("order_support",),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=False,
        is_read_only=True,
    )


class AlphaV2(BaseTool[ExampleInput, ExampleOutput]):
    metadata = metadata("alpha", "2.0.0")
    input_schema = ExampleInput
    output_schema = ExampleOutput


class AlphaV1(BaseTool[ExampleInput, ExampleOutput]):
    metadata = metadata("alpha", "1.0.0")
    input_schema = ExampleInput
    output_schema = ExampleOutput


class BetaV1(BaseTool[ExampleInput, ExampleOutput]):
    metadata = metadata("beta", "1.0.0")
    input_schema = ExampleInput
    output_schema = ExampleOutput


def test_register_and_get_tool_class() -> None:
    registry = ToolRegistry()

    registry.register(AlphaV1)

    assert registry.get("alpha", "1.0.0") is AlphaV1
    assert isinstance(registry.get("alpha", "1.0.0"), type)


def test_register_multiple_tools_and_versions() -> None:
    registry = ToolRegistry()

    registry.register(BetaV1)
    registry.register(AlphaV1)
    registry.register(AlphaV2)

    assert registry.has("alpha", "1.0.0")
    assert registry.has("alpha", "2.0.0")
    assert registry.has("beta", "1.0.0")


def test_duplicate_name_and_version_is_rejected() -> None:
    class DuplicateAlpha(BaseTool[ExampleInput, ExampleOutput]):
        metadata = metadata("alpha", "1.0.0")
        input_schema = ExampleInput
        output_schema = ExampleOutput

    registry = ToolRegistry()
    registry.register(AlphaV1)

    with pytest.raises(
        DuplicateToolRegistrationError,
        match="already registered",
    ):
        registry.register(DuplicateAlpha)


def test_missing_lookup_raises_clear_error() -> None:
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError, match="is not registered"):
        registry.get("missing", "1.0.0")


def test_has_returns_false_for_missing_tool() -> None:
    assert ToolRegistry().has("missing", "1.0.0") is False


def test_list_is_alphabetical_and_deterministic() -> None:
    registry = ToolRegistry()
    registry.register(BetaV1)
    registry.register(AlphaV2)
    registry.register(AlphaV1)

    first = registry.list()
    second = registry.list()

    assert first == (AlphaV1, AlphaV2, BetaV1)
    assert second == first
    assert isinstance(first, tuple)


def test_definitions_use_existing_contract_and_are_json_compatible() -> None:
    registry = ToolRegistry()
    registry.register(BetaV1)
    registry.register(AlphaV1)

    definitions = registry.definitions()

    assert definitions == (AlphaV1.definition(), BetaV1.definition())
    assert json.loads(json.dumps(definitions))[0]["name"] == "alpha"


def test_definitions_are_deterministic_and_not_stored_mutably() -> None:
    registry = ToolRegistry()
    registry.register(AlphaV1)

    expected = registry.definitions()
    returned = registry.definitions()
    returned[0]["name"] = "changed"

    assert registry.definitions() == expected


@pytest.mark.parametrize("invalid", [object, object()])
def test_non_base_tool_declarations_are_rejected(invalid: object) -> None:
    with pytest.raises(TypeError, match="BaseTool subclass"):
        ToolRegistry().register(invalid)  # type: ignore[arg-type]


def test_declaration_modified_after_class_creation_is_rejected() -> None:
    class AlteredTool(BaseTool[ExampleInput, ExampleOutput]):
        metadata = metadata("altered", "1.0.0")
        input_schema = ExampleInput
        output_schema = ExampleOutput

    AlteredTool.input_schema = object  # type: ignore[assignment]

    with pytest.raises(TypeError, match="input_schema"):
        ToolRegistry().register(AlteredTool)


def test_invalid_metadata_modified_after_class_creation_is_rejected() -> None:
    class AlteredMetadataTool(BaseTool[ExampleInput, ExampleOutput]):
        metadata = metadata("altered_metadata", "1.0.0")
        input_schema = ExampleInput
        output_schema = ExampleOutput

    AlteredMetadataTool.metadata = {}  # type: ignore[assignment]

    with pytest.raises(TypeError, match="ToolMetadata"):
        ToolRegistry().register(AlteredMetadataTool)


def test_registry_never_instantiates_or_executes_tools() -> None:
    events = {"instantiated": 0, "executed": 0}

    class NeverRunTool(BaseTool[ExampleInput, ExampleOutput]):
        metadata = metadata("never_run", "1.0.0")
        input_schema = ExampleInput
        output_schema = ExampleOutput

        def __init__(self) -> None:
            events["instantiated"] += 1

        @classmethod
        def execute(cls) -> None:
            events["executed"] += 1

    registry = ToolRegistry()
    registry.register(NeverRunTool)
    registry.get("never_run", "1.0.0")
    registry.list()
    registry.definitions()

    assert events == {"instantiated": 0, "executed": 0}
