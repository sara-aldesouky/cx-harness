"""Tests for provider-neutral tool-call translation boundaries."""

import inspect
import json

import pytest
from pydantic import ValidationError

from app.tools import (
    DuplicateProviderCallIdError,
    MalformedProviderToolCallError,
    MockProviderToolCallAdapter,
    ProviderToolCallAdapter,
    ToolSelectionRequest,
)
from app.tools import provider_adapter as adapter_module


def mock_call(**overrides: object) -> dict[str, object]:
    call: dict[str, object] = {
        "id": "call-001",
        "name": "ping",
        "version": "1.0.0",
        "arguments": {"message": "hello"},
    }
    call.update(overrides)
    return call


def serialize(selections: tuple[ToolSelectionRequest, ...]) -> str:
    return json.dumps(
        [selection.model_dump(mode="json") for selection in selections],
        separators=(",", ":"),
    )


def test_adapter_contract_is_abstract() -> None:
    with pytest.raises(TypeError):
        ProviderToolCallAdapter()


@pytest.mark.parametrize("payload", [{}, {"tool_calls": []}])
def test_no_tool_calls_returns_empty_immutable_collection(payload: object) -> None:
    result = MockProviderToolCallAdapter().translate(payload)

    assert result == ()
    assert isinstance(result, tuple)


def test_single_call_preserves_identity_version_and_arguments() -> None:
    result = MockProviderToolCallAdapter().translate(
        {"tool_calls": [mock_call()]}
    )

    assert result == (
        ToolSelectionRequest(
            call_id="call-001",
            tool_name="ping",
            tool_version="1.0.0",
            arguments={"message": "hello"},
        ),
    )


def test_multiple_calls_preserve_provider_order() -> None:
    result = MockProviderToolCallAdapter().translate(
        {
            "tool_calls": [
                mock_call(id="call-002", arguments={"message": "second"}),
                mock_call(id="call-001", arguments={"message": "first"}),
            ]
        }
    )

    assert tuple(item.call_id for item in result) == ("call-002", "call-001")
    assert tuple(item.arguments["message"] for item in result) == (
        "second",
        "first",
    )


def test_missing_optional_version_is_preserved_for_later_resolution() -> None:
    call = mock_call()
    del call["version"]

    result = MockProviderToolCallAdapter().translate({"tool_calls": [call]})

    assert result[0].tool_version is None


def test_structured_arguments_are_preserved_and_defensively_frozen() -> None:
    arguments = {
        "message": "hello",
        "options": {"labels": ["one", "two"]},
    }
    result = MockProviderToolCallAdapter().translate(
        {"tool_calls": [mock_call(arguments=arguments)]}
    )
    arguments["options"]["labels"].append("changed")  # type: ignore[index,union-attr]

    assert result[0].arguments["options"]["labels"] == ("one", "two")
    with pytest.raises(TypeError):
        result[0].arguments["message"] = "changed"  # type: ignore[index]
    with pytest.raises(ValidationError):
        result[0].call_id = "changed"  # type: ignore[misc]


def test_duplicate_normalized_call_ids_are_rejected() -> None:
    with pytest.raises(DuplicateProviderCallIdError, match="duplicate call IDs"):
        MockProviderToolCallAdapter().translate(
            {
                "tool_calls": [
                    mock_call(id="call-001"),
                    mock_call(id=" call-001 "),
                ]
            }
        )


@pytest.mark.parametrize(
    "call",
    [
        {"name": "ping", "arguments": {"message": "hello"}},
        {"id": "call-001", "arguments": {"message": "hello"}},
        {"id": "call-001", "name": "ping"},
        mock_call(version=1),
        mock_call(arguments="not-an-object"),
        mock_call(extra="unexpected"),
        mock_call(id="   "),
        mock_call(name="   "),
    ],
)
def test_malformed_calls_raise_safe_adapter_error(call: object) -> None:
    with pytest.raises(
        MalformedProviderToolCallError,
        match="mock provider tool-call payload is malformed",
    ) as captured:
        MockProviderToolCallAdapter().translate({"tool_calls": [call]})

    public_message = str(captured.value).lower()
    assert "validation error" not in public_message
    assert "pydantic" not in public_message
    assert "not-an-object" not in public_message


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "not-an-object",
        {"tool_calls": "not-a-list"},
        {"tool_calls": ["not-an-object"]},
        {"tool_calls": [], "unexpected": True},
    ],
)
def test_malformed_top_level_payload_is_rejected(payload: object) -> None:
    with pytest.raises(MalformedProviderToolCallError):
        MockProviderToolCallAdapter().translate(payload)


def test_translation_is_deterministic_and_json_serializable() -> None:
    adapter = MockProviderToolCallAdapter()
    payload = {
        "tool_calls": [
            mock_call(arguments={"message": "hello", "labels": ["a", "b"]})
        ]
    }

    first = adapter.translate(payload)
    second = adapter.translate(payload)

    assert first == second
    assert serialize(first) == serialize(second)
    assert json.loads(serialize(first))[0]["arguments"]["labels"] == ["a", "b"]


def test_adapter_does_not_validate_registry_or_tool_specific_arguments() -> None:
    result = MockProviderToolCallAdapter().translate(
        {
            "tool_calls": [
                mock_call(
                    name="not_registered",
                    version=None,
                    arguments={"arbitrary_business_field": 42},
                )
            ]
        }
    )

    assert result[0].tool_name == "not_registered"
    assert result[0].arguments == {"arbitrary_business_field": 42}


def test_adapter_module_has_no_registry_execution_or_runtime_dependencies() -> None:
    source = inspect.getsource(adapter_module).lower()

    for forbidden in (
        "toolregistry",
        ".execute(",
        "app.providers",
        "sqlalchemy",
        "fastapi",
        "modelrun",
        "promptmanager",
    ):
        assert forbidden not in source
