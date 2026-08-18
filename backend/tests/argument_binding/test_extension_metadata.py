from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from app.argument_binding import (
    ArgumentBindingRequest,
    ProviderToolSelection,
    TrustedArgumentBinder,
    TrustedExecutionValues,
    build_write_argument_binding_policy_registry,
)
from app.argument_binding.metadata import (
    EXTENSION_MAX_COLLECTION_LENGTH,
    EXTENSION_MAX_COUNT,
    EXTENSION_MAX_INTEGER_ABS,
    EXTENSION_MAX_SERIALIZED_BYTES,
    EXTENSION_MAX_STRING_LENGTH,
    RESERVED_EXTENSION_NAMES,
    RESERVED_EXTENSION_PREFIXES,
    _validate_key,
    extension_metadata_copy,
    freeze_extension_metadata,
)
from app.entity_resolution.contracts import EntityResolutionResult, ResolutionStatus


CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000001")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000002")


def trusted(extensions=None) -> TrustedExecutionValues:
    values = {
        "customer_id": CUSTOMER_ID,
        "conversation_id": CONVERSATION_ID,
    }
    if extensions is not None:
        values["extensions"] = extensions
    return TrustedExecutionValues(**values)


@pytest.mark.parametrize("name", sorted(RESERVED_EXTENSION_NAMES))
def test_reserved_extension_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        trusted({name: True})


@pytest.mark.parametrize("prefix", RESERVED_EXTENSION_PREFIXES)
def test_reserved_security_namespaces_are_rejected(prefix: str) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        trusted({prefix + "claim": True})


@pytest.mark.parametrize(
    "extensions",
    [
        {"": 1},
        {" key": 1},
        {"key ": 1},
        {"Upper": 1},
        {"contains.dot": 1},
        {"1starts_wrong": 1},
        {"x" * 65: 1},
        {1: "not a string key"},
    ],
)
def test_invalid_extension_keys_fail_at_contract_construction(extensions) -> None:
    with pytest.raises(ValidationError):
        trusted(extensions)


class DuplicateNormalizedKeys(dict):
    def items(self):
        return (("region", "one"), ("region", "two"))

    def __len__(self):
        return 2


def test_duplicate_normalized_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        freeze_extension_metadata(DuplicateNormalizedKeys())


def test_low_level_validator_rejects_non_string_keys_without_coercion() -> None:
    with pytest.raises(TypeError, match="strings"):
        _validate_key(1)


class ExampleModel(BaseModel):
    value: str


@pytest.mark.parametrize(
    "value",
    [
        UUID(int=1),
        Decimal("1.2"),
        datetime.now(timezone.utc),
        b"secret",
        {"set"},
        lambda: None,
        ExampleModel(value="x"),
        RuntimeError("x"),
        object(),
    ],
)
def test_non_json_or_executable_extension_values_are_rejected(value) -> None:
    with pytest.raises(ValidationError, match="JSON-compatible"):
        trusted({"display_hint": value})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 1.01e308])
def test_nonfinite_or_out_of_range_float_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError, match="finite and bounded"):
        trusted({"score_hint": value})


def test_bounded_metadata_resource_limits() -> None:
    with pytest.raises(ValidationError, match="entry count"):
        trusted({f"key_{index}": index for index in range(EXTENSION_MAX_COUNT + 1)})
    with pytest.raises(ValidationError, match="string"):
        trusted({"display_hint": "x" * (EXTENSION_MAX_STRING_LENGTH + 1)})
    with pytest.raises(ValidationError, match="sequence"):
        trusted({"display_hint": [0] * (EXTENSION_MAX_COLLECTION_LENGTH + 1)})
    with pytest.raises(ValidationError, match="mapping"):
        trusted(
            {
                "display_hint": {
                    f"key_{index}": index
                    for index in range(EXTENSION_MAX_COLLECTION_LENGTH + 1)
                }
            }
        )
    with pytest.raises(ValidationError, match="integer"):
        trusted({"display_hint": EXTENSION_MAX_INTEGER_ABS + 1})
    with pytest.raises(ValidationError, match="nesting"):
        trusted({"display_hint": [[[[[[["too deep"]]]]]]]})
    with pytest.raises(ValidationError, match="serialized size"):
        trusted(
            {
                f"field_{index}": "x" * 700
                for index in range(EXTENSION_MAX_SERIALIZED_BYTES // 700)
            }
        )


def test_valid_metadata_is_sorted_deeply_frozen_and_defensively_copied() -> None:
    original = {
        "region_hint": {"zone_name": "Cairo", "scores": [1, 2.5, None, True]},
        "display_hint": "compact",
    }
    values = trusted(original)
    original["region_hint"]["scores"].append(99)
    assert tuple(values.extensions) == ("display_hint", "region_hint")
    assert values.extensions["region_hint"]["scores"] == (1, 2.5, None, True)
    assert values.model_dump(mode="json")["extensions"] == {
        "display_hint": "compact",
        "region_hint": {
            "scores": [1, 2.5, None, True],
            "zone_name": "Cairo",
        },
    }
    copied = extension_metadata_copy(values.extensions)
    copied["region_hint"]["scores"].append(3)
    assert values.extensions["region_hint"]["scores"] == (1, 2.5, None, True)


class Resolver:
    def resolve(self, request):
        return EntityResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            error_code="order_not_found",
            public_message="The order was not found.",
        )


class SuccessfulResolver:
    def resolve(self, request):
        return EntityResolutionResult(
            status=ResolutionStatus.RESOLVED,
            resolved_entity={
                "entity_type": "order",
                "public_reference": "ORD-10025",
                "relationship": "active",
                "verification_source": "repository_lookup",
                "verified_at": "2026-07-26T12:00:00Z",
            },
            public_message="resolved",
        )


def test_extensions_cannot_affect_binding_arguments_failures_or_audit() -> None:
    values = trusted({"display_hint": "compact", "region_hint": "cairo"})
    request = ArgumentBindingRequest(
        selection=ProviderToolSelection(
            tool_name="cancel_order", arguments={"order_number": "ORD-FAKE"}
        ),
        trusted_values=values,
        current_customer_message="cancel it",
    )
    result = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(), Resolver()
    ).bind(request)
    assert result.bound_selection is None
    assert result.failure.public_message == "The order was not found."
    assert "display_hint" not in result.failure.model_dump_json()
    assert "region_hint" not in result.audit_metadata.model_dump_json()


def test_valid_extensions_are_never_inserted_into_bound_tool_arguments() -> None:
    request = ArgumentBindingRequest(
        selection=ProviderToolSelection(
            tool_name="cancel_order", arguments={"order_number": "ORD-FAKE"}
        ),
        trusted_values=trusted({"display_hint": "compact"}),
        current_customer_message="cancel it",
    )
    result = TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(), SuccessfulResolver()
    ).bind(request)
    assert result.bound_selection.arguments == {"order_number": "ORD-10025"}
    assert "display_hint" not in result.bound_selection.arguments
    assert "display_hint" not in result.audit_metadata.model_dump_json()


def test_construction_without_extensions_remains_compatible() -> None:
    assert trusted().extensions == {}


def test_extension_mapping_input_type_is_enforced() -> None:
    with pytest.raises(TypeError, match="mapping"):
        freeze_extension_metadata([])
