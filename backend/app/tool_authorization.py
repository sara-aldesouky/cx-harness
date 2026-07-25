"""Exact-tool authorization policies independent of providers and ownership."""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional, Protocol, Union

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.identity_roles import PrincipalRole
from app.tools.contracts import GroundingCapability, ToolCategory, ToolMetadata
from app.tools.registry import ToolRegistry


class ToolAuthorizationFailureCode(str, Enum):
    """Stable failures emitted by the exact-tool policy boundary."""

    TOOL_NOT_PERMITTED = "tool_not_permitted"
    UNKNOWN_TOOL = "unknown_tool"
    UNKNOWN_POLICY = "unknown_tool_policy"
    AUTHORIZATION_UNAVAILABLE = "tool_authorization_unavailable"


class ToolAuthorizationPolicyError(RuntimeError):
    """Safe exact-tool authorization failure without policy details."""

    def __init__(
        self, code: ToolAuthorizationFailureCode, public_message: str
    ) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class ToolPermission(BaseModel):
    """Immutable role permission for one exact registered tool version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    tool_version: str
    allowed_roles: frozenset[PrincipalRole]

    @field_validator("tool_name", "tool_version")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool identity must not be blank")
        return normalized

    @field_validator("allowed_roles")
    @classmethod
    def require_roles(
        cls, value: frozenset[PrincipalRole]
    ) -> frozenset[PrincipalRole]:
        if not value:
            raise ValueError("a tool policy must permit at least one role")
        return value


class ToolAuthorizationDecision(BaseModel):
    """Immutable allow-or-deny result produced before ownership checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    failure_code: Optional[ToolAuthorizationFailureCode] = None
    public_message: Optional[str] = None

    @model_validator(mode="after")
    def validate_shape(self) -> "ToolAuthorizationDecision":
        if self.allowed:
            if self.failure_code is not None or self.public_message is not None:
                raise ValueError("allowed decisions must not contain failure data")
        elif self.failure_code is None or not (self.public_message or "").strip():
            raise ValueError("denied decisions require safe failure data")
        return self

    @classmethod
    def allow(cls) -> "ToolAuthorizationDecision":
        return cls(allowed=True)

    @classmethod
    def deny(cls) -> "ToolAuthorizationDecision":
        return cls(
            allowed=False,
            failure_code=ToolAuthorizationFailureCode.TOOL_NOT_PERMITTED,
            public_message="This tool is not available to your role.",
        )


class ToolPolicyRegistry:
    """Append-only registry separating known tools from assigned policies."""

    def __init__(self) -> None:
        self._known_tools: set[tuple[str, str]] = set()
        self._policies: dict[tuple[str, str], ToolPermission] = {}

    def register_tool(self, metadata: ToolMetadata) -> None:
        if not isinstance(metadata, ToolMetadata):
            raise TypeError("metadata must be ToolMetadata")
        key = (metadata.name, metadata.version)
        if key in self._known_tools:
            raise ValueError("tool policy identity is already registered")
        self._known_tools.add(key)

    def set_policy(self, permission: ToolPermission) -> None:
        if not isinstance(permission, ToolPermission):
            raise TypeError("permission must be a ToolPermission")
        key = (permission.tool_name, permission.tool_version)
        if key not in self._known_tools:
            raise ToolAuthorizationPolicyError(
                ToolAuthorizationFailureCode.UNKNOWN_TOOL,
                "The requested tool is not recognized.",
            )
        if key in self._policies:
            raise ValueError("tool policy is already assigned")
        self._policies[key] = permission

    def get(self, tool_name: str, tool_version: str) -> ToolPermission:
        key = (tool_name, tool_version)
        if key not in self._known_tools:
            raise ToolAuthorizationPolicyError(
                ToolAuthorizationFailureCode.UNKNOWN_TOOL,
                "The requested tool is not recognized.",
            )
        try:
            return self._policies[key]
        except KeyError:
            raise ToolAuthorizationPolicyError(
                ToolAuthorizationFailureCode.UNKNOWN_POLICY,
                "Tool access policy is temporarily unavailable.",
            ) from None

    def permissions(self) -> tuple[ToolPermission, ...]:
        return tuple(self._policies[key] for key in sorted(self._policies))

    @classmethod
    def for_runtime(cls, tool_registry: ToolRegistry) -> "ToolPolicyRegistry":
        """Build policies centrally from exact registered metadata."""

        if not isinstance(tool_registry, ToolRegistry):
            raise TypeError("tool_registry must be a ToolRegistry")
        registry = cls()
        for metadata in tool_registry.metadata():
            registry.register_tool(metadata)
            registry.set_policy(
                ToolPermission(
                    tool_name=metadata.name,
                    tool_version=metadata.version,
                    allowed_roles=_approved_roles(metadata),
                )
            )
        return registry


def _approved_roles(metadata: ToolMetadata) -> frozenset[PrincipalRole]:
    """Classify exact tools once at composition, never during execution."""

    if metadata.category is ToolCategory.SYSTEM and not metadata.grounding_capabilities:
        return frozenset({PrincipalRole.INTERNAL_SYSTEM})
    if metadata.grounding_capabilities:
        return frozenset(
            {
                PrincipalRole.CUSTOMER,
                PrincipalRole.CUSTOMER_SUPPORT_AGENT,
                PrincipalRole.SUPERVISOR,
                PrincipalRole.ADMINISTRATOR,
            }
        )
    raise ToolAuthorizationPolicyError(
        ToolAuthorizationFailureCode.UNKNOWN_POLICY,
        "Tool access policy is temporarily unavailable.",
    )


class RequestedToolAuthorizationService(Protocol):
    """Exact-tool authorization behavior required by the gateway."""

    def authorize_tool(
        self,
        role: Union[PrincipalRole, str],
        tool_name: str,
        tool_version: str,
    ) -> ToolAuthorizationDecision: ...


class CentralToolAuthorizationService:
    """Authorize a trusted role against one exact registered tool policy."""

    def __init__(self, registry: ToolPolicyRegistry) -> None:
        if not isinstance(registry, ToolPolicyRegistry):
            raise TypeError("registry must be a ToolPolicyRegistry")
        self._registry = registry

    def authorize_tool(
        self,
        role: Union[PrincipalRole, str],
        tool_name: str,
        tool_version: str,
    ) -> ToolAuthorizationDecision:
        try:
            normalized_role = PrincipalRole(role)
        except (TypeError, ValueError) as error:
            raise ToolAuthorizationPolicyError(
                ToolAuthorizationFailureCode.TOOL_NOT_PERMITTED,
                "This tool is not available to your role.",
            ) from error
        try:
            permission = self._registry.get(tool_name, tool_version)
        except ToolAuthorizationPolicyError:
            raise
        except Exception as error:
            raise ToolAuthorizationPolicyError(
                ToolAuthorizationFailureCode.AUTHORIZATION_UNAVAILABLE,
                "Tool authorization is temporarily unavailable.",
            ) from error
        if normalized_role not in permission.allowed_roles:
            return ToolAuthorizationDecision.deny()
        return ToolAuthorizationDecision.allow()
