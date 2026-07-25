"""In-memory discovery for declared business-tool classes.

The registry answers "which tool is declared?". A future executor will answer
"run this tool". Keeping those responsibilities separate ensures that lookup
never instantiates a tool, executes business logic, or creates runtime results.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.tools.contracts import BaseTool, ToolMetadata


ToolClass = type[BaseTool[Any, Any]]
ToolKey = tuple[str, str]


class DuplicateToolRegistrationError(ValueError):
    """Raised when a tool name and version are already registered."""


class ToolNotFoundError(LookupError):
    """Raised when no registered tool matches a name and version."""


class AmbiguousToolLookupError(LookupError):
    """Raised when name-only lookup matches more than one registered version."""


class ToolRegistry:
    """Append-only, in-memory registry of declared tool classes.

    Registration stores classes rather than instances. After a class is
    registered, the registry exposes only lookup and read operations: it has
    no removal, replacement, instantiation, or execution behavior.
    """

    def __init__(self) -> None:
        self._tools: dict[ToolKey, ToolClass] = {}

    def register(self, tool_class: ToolClass) -> None:
        """Register one valid ``BaseTool`` subclass by name and version."""

        self._validate_tool_class(tool_class)
        key = self._key(tool_class.metadata.name, tool_class.metadata.version)
        if key in self._tools:
            raise DuplicateToolRegistrationError(
                f"tool {key[0]!r} version {key[1]!r} is already registered"
            )
        self._tools[key] = tool_class

    def get(self, name: str, version: str | None = None) -> ToolClass:
        """Return a tool by name, optionally selecting an exact version.

        Name-only lookup is intentionally accepted only when exactly one version
        is registered. This prevents a caller from silently selecting the wrong
        contract after another version is introduced.
        """

        if version is None:
            matches = tuple(
                tool_class
                for (tool_name, _), tool_class in sorted(self._tools.items())
                if tool_name == name
            )
            if not matches:
                raise ToolNotFoundError(f"tool {name!r} is not registered")
            if len(matches) > 1:
                raise AmbiguousToolLookupError(
                    f"tool {name!r} has multiple registered versions; "
                    "specify a version"
                )
            return matches[0]

        key = self._key(name, version)
        try:
            return self._tools[key]
        except KeyError:
            raise ToolNotFoundError(
                f"tool {name!r} version {version!r} is not registered"
            ) from None

    def has(self, name: str, version: str | None = None) -> bool:
        """Return whether a matching tool class is registered."""

        if version is None:
            return any(tool_name == name for tool_name, _ in self._tools)
        return self._key(name, version) in self._tools

    def list(self) -> tuple[ToolClass, ...]:
        """Return registered classes sorted by tool name and version."""

        return tuple(self._tools[key] for key in sorted(self._tools))

    def list_all(self) -> tuple[ToolClass, ...]:
        """Return all registered tool classes in deterministic order."""

        return self.list()

    def list_enabled(self) -> tuple[ToolClass, ...]:
        """Return only enabled tool classes in deterministic order."""

        return tuple(
            tool_class
            for tool_class in self.list()
            if tool_class.metadata.is_enabled
        )

    def metadata(self, *, enabled_only: bool = False) -> tuple[ToolMetadata, ...]:
        """Return immutable metadata declarations without instantiating tools."""

        tools = self.list_enabled() if enabled_only else self.list()
        return tuple(tool_class.metadata for tool_class in tools)

    def definitions(self) -> tuple[dict[str, Any], ...]:
        """Return definitions via each registered class's existing contract."""

        return tuple(tool_class.definition() for tool_class in self.list())

    @staticmethod
    def _key(name: str, version: str) -> ToolKey:
        return name, version

    @staticmethod
    def _validate_tool_class(tool_class: object) -> None:
        """Defensively validate declarations without creating an instance."""

        if not isinstance(tool_class, type) or not issubclass(tool_class, BaseTool):
            raise TypeError("registered tool must be a BaseTool subclass")
        if not isinstance(getattr(tool_class, "metadata", None), ToolMetadata):
            raise TypeError("tool metadata must be a ToolMetadata instance")

        for attribute_name in ("input_schema", "output_schema"):
            schema = getattr(tool_class, attribute_name, None)
            if not isinstance(schema, type) or not issubclass(schema, BaseModel):
                raise TypeError(
                    f"{attribute_name} must be a Pydantic BaseModel class"
                )
