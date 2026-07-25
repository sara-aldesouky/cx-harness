"""Provider-independent authorization policy for read-only business tools."""

from __future__ import annotations

from enum import Enum
from typing import Optional, Protocol, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session, sessionmaker

from app.database.repositories import OrderRepository
from app.tools.contracts import GroundingCapability, ToolCategory, ToolMetadata
from app.tools.execution_request import ToolExecutionRequest


class AuthorizationFailureCode(str, Enum):
    """Stable authorization outcomes safe for application boundaries."""

    ACCESS_DENIED = "access_denied"
    RESOURCE_OWNERSHIP_MISMATCH = "resource_ownership_mismatch"
    UNAUTHORIZED_RESOURCE = "unauthorized_resource"
    AUTHORIZATION_UNAVAILABLE = "authorization_unavailable"
    RESOURCE_NOT_FOUND = "resource_not_found"


class AuthorizationError(RuntimeError):
    """Transport-neutral authorization failure with a safe public message."""

    def __init__(self, code: AuthorizationFailureCode, public_message: str) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


class AuthorizationDecision(BaseModel):
    """Immutable allow-or-deny result produced before tool execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    failure_code: Optional[AuthorizationFailureCode] = None
    public_message: Optional[str] = None

    @model_validator(mode="after")
    def validate_shape(self) -> "AuthorizationDecision":
        if self.allowed:
            if self.failure_code is not None or self.public_message is not None:
                raise ValueError("allowed decisions must not contain failure data")
        elif self.failure_code is None or not (self.public_message or "").strip():
            raise ValueError("denied decisions require safe failure data")
        return self

    @classmethod
    def allow(cls) -> "AuthorizationDecision":
        return cls(allowed=True)

    @classmethod
    def deny(
        cls,
        code: AuthorizationFailureCode,
        message: str = "You do not have access to that resource.",
    ) -> "AuthorizationDecision":
        return cls(allowed=False, failure_code=code, public_message=message)


class OwnershipStatus(str, Enum):
    """Internal ownership lookup state; never returned to customers."""

    OWNED = "owned"
    NOT_OWNED = "not_owned"
    NOT_FOUND = "not_found"


class BusinessResourceOwnershipResolver(Protocol):
    """Read-only ownership lookup required by the authorization policy."""

    def order_status(
        self, customer_id: UUID, order_reference: Union[UUID, str]
    ) -> OwnershipStatus: ...


class SQLAlchemyBusinessResourceOwnershipResolver:
    """Resolve order ownership through the existing read-only repository."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory

    def order_status(
        self, customer_id: UUID, order_reference: Union[UUID, str]
    ) -> OwnershipStatus:
        try:
            with self._session_factory() as session:
                repository = OrderRepository(session)
                order = (
                    repository.get_by_id(order_reference)
                    if isinstance(order_reference, UUID)
                    else repository.get_by_order_number(order_reference)
                )
        except Exception as error:
            raise AuthorizationError(
                AuthorizationFailureCode.AUTHORIZATION_UNAVAILABLE,
                "Authorization is temporarily unavailable.",
            ) from error
        if order is None:
            return OwnershipStatus.NOT_FOUND
        if order.customer_id == customer_id:
            return OwnershipStatus.OWNED
        return OwnershipStatus.NOT_OWNED


class ToolAuthorizationService(Protocol):
    """Authorization behavior consumed by the execution gateway."""

    def authorize(
        self, request: ToolExecutionRequest, metadata: ToolMetadata
    ) -> AuthorizationDecision: ...


class OwnershipAuthorizationService:
    """Apply declarative identity and ownership policy before tool execution.

    Knowledge-only tools are public. Transactional tools fail closed unless
    their metadata requires trusted identity. Protected order references deny
    both absence and ownership mismatch before tool execution; the transport
    boundary exposes the same generic not-found response for both outcomes.
    """

    def __init__(self, resolver: BusinessResourceOwnershipResolver) -> None:
        if not callable(getattr(resolver, "order_status", None)):
            raise TypeError("resolver must provide order_status()")
        self._resolver = resolver

    def authorize(
        self, request: ToolExecutionRequest, metadata: ToolMetadata
    ) -> AuthorizationDecision:
        if not isinstance(request, ToolExecutionRequest):
            raise TypeError("request must be a ToolExecutionRequest")
        if not isinstance(metadata, ToolMetadata):
            raise TypeError("metadata must be ToolMetadata")

        capabilities = frozenset(metadata.grounding_capabilities)
        if capabilities == {GroundingCapability.KNOWLEDGE}:
            return AuthorizationDecision.allow()
        if metadata.category is ToolCategory.SYSTEM and not capabilities:
            return AuthorizationDecision.allow()

        if not metadata.is_read_only or not metadata.requires_customer_identity:
            return AuthorizationDecision.deny(
                AuthorizationFailureCode.ACCESS_DENIED
            )
        customer_id = request.context.customer_id
        if customer_id is None:
            return AuthorizationDecision.deny(
                AuthorizationFailureCode.ACCESS_DENIED
            )

        requested_customer = request.arguments.get("customer_id")
        if requested_customer is not None and str(requested_customer) != str(customer_id):
            return AuthorizationDecision.deny(
                AuthorizationFailureCode.RESOURCE_OWNERSHIP_MISMATCH
            )

        if metadata.requires_order_ownership:
            order_reference = request.arguments.get("order_number")
            uses_order_id = order_reference is None
            if uses_order_id:
                order_reference = request.arguments.get("order_id")
            if order_reference is not None:
                if not isinstance(order_reference, UUID):
                    normalized_reference = str(order_reference)
                    if uses_order_id:
                        try:
                            order_reference = UUID(normalized_reference)
                        except ValueError:
                            order_reference = normalized_reference
                    else:
                        order_reference = normalized_reference
                try:
                    ownership = self._resolver.order_status(
                        customer_id, order_reference
                    )
                except AuthorizationError:
                    raise
                except Exception as error:
                    raise AuthorizationError(
                        AuthorizationFailureCode.AUTHORIZATION_UNAVAILABLE,
                        "Authorization is temporarily unavailable.",
                    ) from error
                if ownership is OwnershipStatus.NOT_OWNED:
                    return AuthorizationDecision.deny(
                        AuthorizationFailureCode.UNAUTHORIZED_RESOURCE
                    )
                if ownership is OwnershipStatus.NOT_FOUND:
                    return AuthorizationDecision.deny(
                        AuthorizationFailureCode.RESOURCE_NOT_FOUND,
                        "The requested resource was not found.",
                    )
                if ownership is not OwnershipStatus.OWNED:
                    raise AuthorizationError(
                        AuthorizationFailureCode.AUTHORIZATION_UNAVAILABLE,
                        "Authorization is temporarily unavailable.",
                    )

        return AuthorizationDecision.allow()
