"""Unit tests for declarative business-tool contracts."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from app.tools import (
    BaseTool,
    ExecutionContext,
    ToolCategory,
    ToolMetadata,
    ToolResult,
)


class ExampleInput(BaseModel):
    order_id: str


class ExampleOutput(BaseModel):
    status: str


def valid_metadata(**overrides: object) -> ToolMetadata:
    values = {
        "name": "get_order_status",
        "version": "1.0.0",
        "description": "Return the current status of a customer's order.",
        "category": ToolCategory.ORDER,
        "supported_use_cases": ("order_status", "delivery_tracking"),
        "requires_customer_identity": True,
        "requires_order_ownership": True,
        "requires_policy_check": False,
        "is_read_only": True,
    }
    values.update(overrides)
    return ToolMetadata(**values)


class ExampleTool(BaseTool[ExampleInput, ExampleOutput]):
    metadata = valid_metadata()
    input_schema = ExampleInput
    output_schema = ExampleOutput

    def execute(
        self,
        context: ExecutionContext,
        input_model: ExampleInput,
    ) -> ToolResult[ExampleOutput]:
        return ToolResult[ExampleOutput](
            status="success",
            data=ExampleOutput(status=input_model.order_id),
        )


def test_valid_metadata_is_normalized_and_serializable():
    metadata = valid_metadata(
        name="  get_order_status  ",
        description="  Return order status.  ",
        supported_use_cases=[" order_status ", "delivery_tracking"],
    )

    assert metadata.name == "get_order_status"
    assert metadata.description == "Return order status."
    assert metadata.supported_use_cases == ("order_status", "delivery_tracking")
    assert metadata.model_dump(mode="json")["category"] == "order"
    json.dumps(metadata.model_dump(mode="json"))


def test_metadata_is_immutable():
    metadata = valid_metadata()

    with pytest.raises(ValidationError):
        metadata.name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("value", ["", "   "])
def test_metadata_rejects_empty_required_text(field, value):
    with pytest.raises(ValidationError, match="value must not be empty"):
        valid_metadata(**{field: value})


@pytest.mark.parametrize(
    "version",
    ["1", "1.0", "v1.0.0", "1.0.0.0", "01.0.0", "1.01.0", "1.0.01"],
)
def test_metadata_rejects_invalid_semantic_versions(version):
    with pytest.raises(ValidationError, match="semantic-version format"):
        valid_metadata(version=version)


@pytest.mark.parametrize(
    "use_cases",
    [(), ("",), ("order_status", "   ")],
)
def test_metadata_rejects_missing_or_empty_use_cases(use_cases):
    with pytest.raises(ValidationError, match="supported_use_cases|use cases"):
        valid_metadata(supported_use_cases=use_cases)


def test_metadata_rejects_duplicate_use_cases_after_normalization():
    with pytest.raises(ValidationError, match="duplicates"):
        valid_metadata(supported_use_cases=("order_status", " order_status "))


def test_tool_declares_metadata_and_schema_boundaries():
    tool = ExampleTool()

    assert tool.metadata == ExampleTool.metadata
    assert tool.name == "get_order_status"
    assert tool.version == "1.0.0"
    assert tool.description == ExampleTool.metadata.description
    assert tool.category is ToolCategory.ORDER
    assert tool.input_schema is ExampleInput
    assert tool.output_schema is ExampleOutput
    assert tool.metadata.requires_customer_identity is True
    assert tool.metadata.requires_order_ownership is True
    assert tool.metadata.requires_policy_check is False
    assert tool.metadata.is_read_only is True


def test_tool_rejects_non_pydantic_input_schema():
    with pytest.raises(TypeError, match="input_schema must be a Pydantic"):

        class InvalidInputTool(BaseTool[ExampleInput, ExampleOutput]):
            metadata = valid_metadata()
            input_schema = dict
            output_schema = ExampleOutput


def test_tool_rejects_invalid_metadata_declaration():
    with pytest.raises(TypeError, match="metadata must be a ToolMetadata"):

        class InvalidMetadataTool(BaseTool[ExampleInput, ExampleOutput]):
            metadata = {"name": "not-validated"}
            input_schema = ExampleInput
            output_schema = ExampleOutput


def test_tool_rejects_non_pydantic_output_schema():
    with pytest.raises(TypeError, match="output_schema must be a Pydantic"):

        class InvalidOutputTool(BaseTool[ExampleInput, ExampleOutput]):
            metadata = valid_metadata()
            input_schema = ExampleInput
            output_schema = dict


def test_tool_definition_is_deterministic_and_json_serializable():
    first = ExampleTool.definition()
    second = ExampleTool.definition()

    assert first == second
    assert json.loads(json.dumps(first)) == first
    assert first["category"] == "order"
    assert first["supported_use_cases"] == ["order_status", "delivery_tracking"]
    assert first["grounding_capabilities"] == []
    assert first["requires_customer_identity"] is True
    assert first["requires_order_ownership"] is True
    assert first["requires_policy_check"] is False
    assert first["is_read_only"] is True


def test_tool_definition_includes_input_and_output_json_schemas():
    definition = ExampleTool.definition()

    assert definition["input_schema"] == ExampleInput.model_json_schema()
    assert definition["output_schema"] == ExampleOutput.model_json_schema()
    assert definition["input_schema"]["required"] == ["order_id"]
    assert definition["output_schema"]["required"] == ["status"]
