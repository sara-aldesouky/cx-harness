"""Provider-neutral correlated outcome for one completed tool result."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticSerializationError

from app.tools.execution_request import ToolExecutionRequest
from app.tools.immutable_json import freeze_json, json_copy
from app.tools.result import ToolError, ToolResult, ToolStatus
from app.data_protection import DataProtectionService, privacy_service
from app.security_audit import (
    AuditCategory,
    AuditResult,
    AuditSeverity,
    SecurityEventType,
    security_audit_recorder,
)


class ToolExecutionOutcomeError(ValueError):
    """Base error for correlated outcome construction failures."""


class InvalidToolExecutionOutcomeRequestError(ToolExecutionOutcomeError):
    """Raised when correlation does not start from ToolExecutionRequest."""


class InvalidToolExecutionOutcomeResultError(ToolExecutionOutcomeError):
    """Raised when the supplied object is not the existing ToolResult contract."""


class ToolExecutionOutcomeIdentityMismatchError(ToolExecutionOutcomeError):
    """Raised when result identity, if supplied, contradicts request identity."""


class UnsupportedToolResultStateError(ToolExecutionOutcomeError):
    """Raised when a malformed result bypassed the ToolResult invariants."""


class NonSerializableToolOutputError(ToolExecutionOutcomeError):
    """Raised when successful typed data cannot be represented safely as JSON."""


class ToolExecutionOutcome(BaseModel):
    """Immutable provider-neutral outcome correlated to one original call."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    call_id: str
    tool_name: str
    tool_version: str
    status: ToolStatus
    output: Optional[Mapping[str, Any]] = None
    error: Optional[ToolError] = None

    @field_validator("call_id", "tool_name", "tool_version")
    @classmethod
    def validate_required_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("output")
    @classmethod
    def freeze_output(
        cls, value: Optional[Mapping[str, Any]]
    ) -> Optional[Mapping[str, Any]]:
        return None if value is None else freeze_json(value)

    @model_validator(mode="after")
    def validate_status_payload(self) -> ToolExecutionOutcome:
        if self.status is ToolStatus.SUCCESS:
            if self.output is None:
                raise ValueError("successful outcomes require output")
            if self.error is not None:
                raise ValueError("successful outcomes must not include an error")
        else:
            if self.output is not None:
                raise ValueError("failed outcomes must not include output")
            if self.error is None:
                raise ValueError("failed outcomes require an error")
        return self

    @field_serializer("output")
    def serialize_output(
        self, value: Optional[Mapping[str, Any]]
    ) -> Optional[dict[str, Any]]:
        return None if value is None else json_copy(value)


class ToolExecutionOutcomeFactory:
    """Correlate an existing executor result with its immutable request."""

    def create(
        self,
        request: ToolExecutionRequest,
        result: ToolResult,
    ) -> ToolExecutionOutcome:
        """Build an outcome without execution, auditing, or provider formatting."""

        if not isinstance(request, ToolExecutionRequest):
            raise InvalidToolExecutionOutcomeRequestError(
                "request must be a ToolExecutionRequest"
            )
        if not isinstance(result, ToolResult):
            raise InvalidToolExecutionOutcomeResultError(
                "result must be a ToolResult"
            )

        self._verify_optional_result_identity(request, result)

        if result.status is ToolStatus.SUCCESS:
            if not isinstance(result.data, BaseModel) or result.error is not None:
                raise UnsupportedToolResultStateError(
                    "tool result contains an unsupported success state"
                )
            try:
                output = result.data.model_dump(mode="json")
            except (PydanticSerializationError, TypeError, ValueError) as error:
                raise NonSerializableToolOutputError(
                    "successful tool output is not JSON serializable"
                ) from error
            protected_output = self._data_protection.protect_mapping(output)
            if protected_output != output:
                security_audit_recorder.record(
                    SecurityEventType.DATA_REDACTION_PERFORMED,
                    severity=AuditSeverity.INFO,
                    result=AuditResult.SUCCESS,
                    category=AuditCategory.PRIVACY,
                    role=request.context.principal_role,
                    tool_name=request.tool_name,
                    tool_version=request.tool_version,
                    correlation_id=request.context.trace_id,
                    request_id=request.context.execution_id,
                    customer_id=request.context.customer_id,
                    session_id=request.context.conversation_id,
                )
            return ToolExecutionOutcome(
                call_id=request.call_id,
                tool_name=request.tool_name,
                tool_version=request.tool_version,
                status=result.status,
                output=protected_output,
                error=None,
            )

        if result.status is ToolStatus.FAILURE:
            if result.data is not None or not isinstance(result.error, ToolError):
                raise UnsupportedToolResultStateError(
                    "tool result contains an unsupported failure state"
                )
            return ToolExecutionOutcome(
                call_id=request.call_id,
                tool_name=request.tool_name,
                tool_version=request.tool_version,
                status=result.status,
                output=None,
                error=ToolError.model_validate(result.error.model_dump()),
            )

        raise UnsupportedToolResultStateError(
            "tool result contains an unsupported status"
        )

    @staticmethod
    def _verify_optional_result_identity(
        request: ToolExecutionRequest,
        result: ToolResult,
    ) -> None:
        result_name = getattr(result, "tool_name", None)
        result_version = getattr(result, "tool_version", None)
        if result_name is not None and result_name != request.tool_name:
            raise ToolExecutionOutcomeIdentityMismatchError(
                "tool result name does not match the execution request"
            )
        if result_version is not None and result_version != request.tool_version:
            raise ToolExecutionOutcomeIdentityMismatchError(
                "tool result version does not match the execution request"
            )
    def __init__(
        self, data_protection: DataProtectionService = privacy_service
    ) -> None:
        if not isinstance(data_protection, DataProtectionService):
            raise TypeError("data_protection must be a DataProtectionService")
        self._data_protection = data_protection
