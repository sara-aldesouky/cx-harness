"""Declarative, provider-independent business-tool contracts."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator

from app.tools.context import ExecutionContext
from app.tools.result import ToolResult


class ToolCategory(str, Enum):
    """Stable high-level categories for business tools."""

    CUSTOMER = "customer"
    ORDER = "order"
    PAYMENT = "payment"
    SUPPORT = "support"
    POLICY = "policy"
    SYSTEM = "system"


class GroundingCapability(str, Enum):
    """Business fact domains for which a tool can provide trusted evidence."""

    CUSTOMER = "customer"
    ORDER = "order"
    DELIVERY = "delivery"
    PAYMENT = "payment"
    REFUND = "refund"
    KNOWLEDGE = "knowledge"


_SEMANTIC_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class ToolMetadata(BaseModel):
    """Immutable identity and declared safety characteristics of one tool."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    description: str
    category: ToolCategory
    supported_use_cases: tuple[str, ...]
    grounding_capabilities: tuple[GroundingCapability, ...] = ()
    requires_customer_identity: bool
    requires_order_ownership: bool
    requires_policy_check: bool
    is_read_only: bool
    is_enabled: bool = True

    @field_validator("name", "description")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        """Normalize required text and reject blank declarations."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("version")
    @classmethod
    def validate_semantic_version(cls, value: str) -> str:
        """Require a normalized Semantic Versioning 2.0 value."""

        normalized = value.strip()
        if not _SEMANTIC_VERSION_PATTERN.fullmatch(normalized):
            raise ValueError("version must use semantic-version format, such as 1.0.0")
        return normalized

    @field_validator("supported_use_cases")
    @classmethod
    def validate_supported_use_cases(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Normalize use cases while preserving deterministic declaration order."""

        if not values:
            raise ValueError("supported_use_cases must contain at least one value")

        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("supported use cases must not be empty")
        if len(set(normalized)) != len(normalized):
            raise ValueError("supported use cases must not contain duplicates")
        return normalized

    @field_validator("grounding_capabilities")
    @classmethod
    def validate_grounding_capabilities(
        cls, values: tuple[GroundingCapability, ...]
    ) -> tuple[GroundingCapability, ...]:
        """Reject duplicate evidence declarations while preserving order."""

        if len(set(values)) != len(values):
            raise ValueError("grounding capabilities must not contain duplicates")
        return values


InputModelT = TypeVar("InputModelT", bound=BaseModel)
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


class BaseTool(ABC, Generic[InputModelT, OutputModelT]):
    """Provider-independent declaration and execution boundary for tools."""

    metadata: ClassVar[ToolMetadata]
    input_schema: ClassVar[type[BaseModel]]
    output_schema: ClassVar[type[BaseModel]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Validate concrete declarations when a tool class is defined."""

        super().__init_subclass__(**kwargs)
        metadata = cls.__dict__.get("metadata")
        if not isinstance(metadata, ToolMetadata):
            raise TypeError("tool metadata must be a ToolMetadata instance")
        cls._validate_schema_type("input_schema")
        cls._validate_schema_type("output_schema")

    @classmethod
    def _validate_schema_type(cls, attribute_name: str) -> None:
        schema = cls.__dict__.get(attribute_name)
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError(f"{attribute_name} must be a Pydantic BaseModel class")

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def version(self) -> str:
        return self.metadata.version

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def category(self) -> ToolCategory:
        return self.metadata.category

    @abstractmethod
    def execute(
        self,
        context: ExecutionContext,
        input_model: InputModelT,
    ) -> ToolResult[OutputModelT]:
        """Execute validated input within trusted runtime context."""

        raise NotImplementedError

    @classmethod
    def definition(cls) -> dict[str, Any]:
        """Return a deterministic, provider-neutral, JSON-serializable definition."""

        metadata = cls.metadata.model_dump(mode="json")
        return {
            "name": metadata["name"],
            "version": metadata["version"],
            "description": metadata["description"],
            "category": metadata["category"],
            "supported_use_cases": metadata["supported_use_cases"],
            "grounding_capabilities": metadata["grounding_capabilities"],
            "requires_customer_identity": metadata[
                "requires_customer_identity"
            ],
            "requires_order_ownership": metadata["requires_order_ownership"],
            "requires_policy_check": metadata["requires_policy_check"],
            "is_read_only": metadata["is_read_only"],
            "is_enabled": metadata["is_enabled"],
            "input_schema": cls.input_schema.model_json_schema(),
            "output_schema": cls.output_schema.model_json_schema(),
        }
