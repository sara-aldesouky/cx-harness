"""Immutable, provider- and domain-neutral write operation contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Generic, Mapping, Optional, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.tools.context import ExecutionContext
from app.tools.immutable_json import freeze_json, json_copy


class WriteStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class WriteFailurePhase(str, Enum):
    VALIDATION = "validation"
    TRANSACTION = "transaction"
    INFRASTRUCTURE = "infrastructure"


class WriteSecurityEnvelope(BaseModel):
    """Trusted proof that existing Stage 11 gates allowed this operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authenticated: bool
    role_policy_allowed: bool
    tool_authorized: bool
    ownership_authorized: bool

    @property
    def fully_authorized(self) -> bool:
        return all(
            (
                self.authenticated,
                self.role_policy_allowed,
                self.tool_authorized,
                self.ownership_authorized,
            )
        )


class WriteExecutionContext(BaseModel):
    """Immutable trusted identity and request metadata for one future write.

    This context is constructed after the existing authentication, role, tool,
    and ownership gates. It is never populated from model-generated arguments.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_context: ExecutionContext
    security: WriteSecurityEnvelope
    request_id: UUID
    correlation_id: UUID
    requested_at: datetime

    @model_validator(mode="after")
    def require_trusted_identity(self) -> "WriteExecutionContext":
        if self.execution_context.customer_id is None:
            raise ValueError("write execution requires trusted customer identity")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must include a timezone")
        return self


class WriteValidationDecision(BaseModel):
    """Reusable business-rule outcome produced before transaction entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    failure_code: Optional[str] = None
    public_message: Optional[str] = None

    @field_validator("failure_code", "public_message")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("failure text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_shape(self) -> "WriteValidationDecision":
        if self.allowed and (self.failure_code is not None or self.public_message is not None):
            raise ValueError("allowed validation cannot contain failure data")
        if not self.allowed and (
            self.failure_code is None or self.public_message is None
        ):
            raise ValueError("denied validation requires safe failure data")
        return self

    @classmethod
    def allow(cls) -> "WriteValidationDecision":
        return cls(allowed=True)

    @classmethod
    def deny(cls, code: str, message: str) -> "WriteValidationDecision":
        return cls(allowed=False, failure_code=code, public_message=message)


class WriteError(BaseModel):
    """Safe deterministic failure returned by the framework."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    error_code: str
    public_message: str
    phase: WriteFailurePhase

    @field_validator("error_code", "public_message")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("write error text must not be blank")
        return normalized


OutputT = TypeVar("OutputT", bound=BaseModel)


class WriteResult(BaseModel, Generic[OutputT]):
    """Standard immutable success-or-failure response for every future write."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    status: WriteStatus
    outcome: Optional[OutputT] = None
    error: Optional[WriteError] = None
    message: str
    metadata: Any = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("write result message must not be blank")
        return normalized

    @field_validator("metadata")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("metadata must be a mapping")
        return freeze_json(value)

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return json_copy(value)

    @model_validator(mode="after")
    def validate_shape(self) -> "WriteResult[OutputT]":
        if self.status is WriteStatus.SUCCESS:
            if self.outcome is None or self.error is not None:
                raise ValueError("successful writes require only an outcome")
        elif self.outcome is not None or self.error is None:
            raise ValueError("failed writes require only an error")
        return self


class WriteAuditEvent(BaseModel):
    """Safe infrastructure event emitted after validation or transaction end."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_name: str
    operation_version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: UUID
    correlation_id: UUID
    resource_reference: Optional[str] = None
    status: WriteStatus
    business_change_applied: Optional[bool] = None
    failure_phase: Optional[WriteFailurePhase] = None
    failure_code: Optional[str] = None

    @field_validator("resource_reference")
    @classmethod
    def normalize_resource_reference(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("resource reference must not be blank")
        return normalized


InputT = TypeVar("InputT", bound=BaseModel)
TransactionT = TypeVar("TransactionT")


class BaseWriteOperation(ABC, Generic[InputT, OutputT, TransactionT]):
    """Business-only contract implemented by future write capabilities."""

    name: str
    version: str
    input_schema: type[InputT]
    output_schema: type[OutputT]

    def audit_reference(
        self, input_model: InputT, outcome: Optional[OutputT] = None
    ) -> Optional[str]:
        """Return a customer-safe resource reference for the audit event."""

        return None

    def success_message(self, outcome: OutputT) -> str:
        """Return a safe deterministic message for a successful outcome."""

        return "The requested change was completed successfully."

    def business_change_applied(self, outcome: OutputT) -> bool:
        """Classify a successful outcome for accurate idempotency auditing.

        Most successful operations apply a change. Idempotent operations whose
        output can also represent an existing logical result override this
        method so retry attempts are not reported as repeated business changes.
        """

        return True

    @abstractmethod
    def validate(
        self, context: WriteExecutionContext, input_model: InputT
    ) -> WriteValidationDecision:
        """Evaluate operation-specific business rules without transaction control."""

    @abstractmethod
    def apply(
        self,
        context: WriteExecutionContext,
        input_model: InputT,
        transaction: TransactionT,
    ) -> OutputT:
        """Apply business behavior inside the framework-owned transaction."""
