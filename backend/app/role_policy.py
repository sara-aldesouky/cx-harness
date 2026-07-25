"""Provider-independent role policy for registered business capabilities."""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional, Protocol, Union

from pydantic import BaseModel, ConfigDict, model_validator

from app.identity_roles import PrincipalRole
from app.tools.contracts import GroundingCapability, ToolCategory, ToolMetadata


class RolePolicyFailureCode(str, Enum):
    """Stable, transport-neutral role-policy failures."""

    INSUFFICIENT_ROLE = "insufficient_role"
    UNKNOWN_ROLE = "unknown_role"
    POLICY_UNAVAILABLE = "policy_unavailable"
    POLICY_EVALUATION_FAILURE = "policy_evaluation_failure"


class RolePolicyError(RuntimeError):
    """Safe role-policy failure that contains no policy internals."""

    def __init__(self, code: RolePolicyFailureCode, public_message: str) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class RolePolicyDecision(BaseModel):
    """Immutable capability decision returned before business execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    failure_code: Optional[RolePolicyFailureCode] = None
    public_message: Optional[str] = None

    @model_validator(mode="after")
    def validate_shape(self) -> "RolePolicyDecision":
        if self.allowed:
            if self.failure_code is not None or self.public_message is not None:
                raise ValueError("allowed decisions must not contain failure data")
        elif self.failure_code is None or not (self.public_message or "").strip():
            raise ValueError("denied decisions require safe failure data")
        return self

    @classmethod
    def allow(cls) -> "RolePolicyDecision":
        return cls(allowed=True)

    @classmethod
    def deny(cls, code: RolePolicyFailureCode) -> "RolePolicyDecision":
        return cls(
            allowed=False,
            failure_code=code,
            public_message="Your role does not permit this operation.",
        )


class ToolRolePolicyService(Protocol):
    """Role evaluation behavior consumed by the execution gateway."""

    def evaluate(
        self, role: Union[PrincipalRole, str], metadata: ToolMetadata
    ) -> RolePolicyDecision: ...


_CUSTOMER_CAPABILITIES = frozenset(GroundingCapability)
_BUSINESS_CAPABILITIES = frozenset(GroundingCapability)


DEFAULT_ROLE_POLICIES: Mapping[PrincipalRole, frozenset[GroundingCapability]] = (
    MappingProxyType(
        {
            PrincipalRole.CUSTOMER: _CUSTOMER_CAPABILITIES,
            PrincipalRole.CUSTOMER_SUPPORT_AGENT: _BUSINESS_CAPABILITIES,
            PrincipalRole.SUPERVISOR: _BUSINESS_CAPABILITIES,
            PrincipalRole.ADMINISTRATOR: _BUSINESS_CAPABILITIES,
            PrincipalRole.INTERNAL_SYSTEM: _BUSINESS_CAPABILITIES,
        }
    )
)


class CapabilityRolePolicyService:
    """Evaluate centralized role-to-capability declarations.

    Business tools remain unaware of roles. Adding a role or changing its
    capability set changes this policy table, not tool or provider code.
    Resource ownership remains the separate responsibility of Stage 11.2.
    """

    def __init__(
        self,
        policies: Mapping[
            PrincipalRole, frozenset[GroundingCapability]
        ] = DEFAULT_ROLE_POLICIES,
    ) -> None:
        if not policies:
            raise RolePolicyError(
                RolePolicyFailureCode.POLICY_UNAVAILABLE,
                "Access policy is temporarily unavailable.",
            )
        try:
            self._policies = MappingProxyType(
                {
                    PrincipalRole(role): frozenset(
                        GroundingCapability(capability)
                        for capability in capabilities
                    )
                    for role, capabilities in policies.items()
                }
            )
        except (TypeError, ValueError) as error:
            raise RolePolicyError(
                RolePolicyFailureCode.POLICY_UNAVAILABLE,
                "Access policy is temporarily unavailable.",
            ) from error

    def evaluate(
        self, role: Union[PrincipalRole, str], metadata: ToolMetadata
    ) -> RolePolicyDecision:
        if not isinstance(metadata, ToolMetadata):
            raise TypeError("metadata must be ToolMetadata")
        try:
            normalized_role = PrincipalRole(role)
        except (TypeError, ValueError) as error:
            raise RolePolicyError(
                RolePolicyFailureCode.UNKNOWN_ROLE,
                "The authenticated role is not recognized.",
            ) from error

        allowed_capabilities = self._policies.get(normalized_role)
        if allowed_capabilities is None:
            raise RolePolicyError(
                RolePolicyFailureCode.POLICY_UNAVAILABLE,
                "Access policy is temporarily unavailable.",
            )

        capabilities = frozenset(metadata.grounding_capabilities)
        if capabilities == {GroundingCapability.KNOWLEDGE}:
            return RolePolicyDecision.allow()
        if metadata.category is ToolCategory.SYSTEM and not capabilities:
            return (
                RolePolicyDecision.allow()
                if normalized_role is PrincipalRole.INTERNAL_SYSTEM
                else RolePolicyDecision.deny(
                    RolePolicyFailureCode.INSUFFICIENT_ROLE
                )
            )
        if not capabilities:
            return RolePolicyDecision.deny(
                RolePolicyFailureCode.POLICY_EVALUATION_FAILURE
            )
        if capabilities.issubset(allowed_capabilities):
            return RolePolicyDecision.allow()
        return RolePolicyDecision.deny(RolePolicyFailureCode.INSUFFICIENT_ROLE)
