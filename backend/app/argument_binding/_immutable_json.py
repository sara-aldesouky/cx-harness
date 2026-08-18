"""Private immutable JSON helpers that keep argument binding self-contained."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


def freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def json_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: json_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [json_copy(item) for item in value]
    return value
