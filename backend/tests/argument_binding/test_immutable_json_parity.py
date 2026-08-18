from __future__ import annotations

from app.argument_binding._immutable_json import freeze_json as binding_freeze
from app.argument_binding._immutable_json import json_copy as binding_copy
from app.tools.immutable_json import freeze_json as shared_freeze
from app.tools.immutable_json import json_copy as shared_copy


def test_overlapping_immutable_json_domain_has_behavioral_parity() -> None:
    source = {
        "text": "hello",
        "flag": True,
        "integer": 7,
        "float": 2.5,
        "nothing": None,
        "list": [1, {"nested": ("x", False)}],
    }
    binding = binding_freeze(source)
    shared = shared_freeze(source)
    source["list"].append("mutation")
    assert binding_copy(binding) == shared_copy(shared)
    assert binding_copy(binding) == {
        "text": "hello",
        "flag": True,
        "integer": 7,
        "float": 2.5,
        "nothing": None,
        "list": [1, {"nested": ["x", False]}],
    }


def test_mapping_order_and_unsupported_object_parity_are_intentional() -> None:
    source = {"z": 1, "a": 2}
    assert list(binding_copy(binding_freeze(source))) == ["z", "a"]
    assert binding_copy(binding_freeze(source)) == shared_copy(shared_freeze(source))
    unsupported = object()
    assert binding_freeze(unsupported) is unsupported
    assert shared_freeze(unsupported) is unsupported
