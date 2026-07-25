"""Single-request application boundary over the existing ToolExecutor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.tools.execution_request import ToolExecutionRequest
from app.tools.executor import ToolExecutor
from app.tools.immutable_json import json_copy
from app.tools.registry import ToolNotFoundError, ToolRegistry
from app.tools.result import ToolResult
from app.tools.result import ToolError, ToolStatus
from app.security_audit import (
    AuditCategory,
    AuditResult,
    AuditSeverity,
    SecurityAuditRecorder,
    SecurityEventType,
    security_audit_recorder,
)

if TYPE_CHECKING:
    from app.authorization import ToolAuthorizationService
    from app.role_policy import ToolRolePolicyService
    from app.tool_authorization import RequestedToolAuthorizationService


class SingleToolExecutionGatewayError(Exception):
    """Base error for failures added specifically by the gateway boundary."""


class InvalidToolExecutionGatewayRequestError(
    SingleToolExecutionGatewayError, TypeError
):
    """Raised when execution is attempted without ToolExecutionRequest."""


class DisabledToolExecutionError(SingleToolExecutionGatewayError):
    """Raised when a tool was disabled after selection and before execution."""


class ToolInputRehydrationError(SingleToolExecutionGatewayError):
    """Raised when validated JSON cannot be rebuilt as the registered input model."""


class SingleToolExecutionGateway:
    """Adapt exactly one trusted request to the existing execution engine.

    Exact lookup and enablement are checked immediately before delegation to
    protect against runtime registry changes. Tool construction, invocation,
    result verification, auditing, and persistence remain exclusively owned by
    ``ToolExecutor``.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        authorization_service: ToolAuthorizationService | None = None,
        role_policy_service: ToolRolePolicyService | None = None,
        tool_authorization_service: RequestedToolAuthorizationService | None = None,
        security_audit: SecurityAuditRecorder = security_audit_recorder,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        if not isinstance(executor, ToolExecutor):
            raise TypeError("executor must be a ToolExecutor")
        self._registry = registry
        self._executor = executor
        if authorization_service is not None and not callable(
            getattr(authorization_service, "authorize", None)
        ):
            raise TypeError("authorization_service must provide authorize()")
        self._authorization_service = authorization_service
        if role_policy_service is not None and not callable(
            getattr(role_policy_service, "evaluate", None)
        ):
            raise TypeError("role_policy_service must provide evaluate()")
        self._role_policy_service = role_policy_service
        if tool_authorization_service is not None and not callable(
            getattr(tool_authorization_service, "authorize_tool", None)
        ):
            raise TypeError(
                "tool_authorization_service must provide authorize_tool()"
            )
        self._tool_authorization_service = tool_authorization_service
        if not isinstance(security_audit, SecurityAuditRecorder):
            raise TypeError("security_audit must be a SecurityAuditRecorder")
        self._security_audit = security_audit

    def execute(self, request: ToolExecutionRequest) -> ToolResult:
        """Execute one exact request once and return the executor result unchanged."""

        # Security policy modules depend on tool contracts. Importing their
        # exception types lazily keeps dependency direction acyclic while the
        # public ``app.tools`` package performs its compatibility exports.
        from app.authorization import AuthorizationError
        from app.role_policy import RolePolicyError
        from app.tool_authorization import ToolAuthorizationPolicyError

        if not isinstance(request, ToolExecutionRequest):
            raise InvalidToolExecutionGatewayRequestError(
                "request must be a ToolExecutionRequest"
            )

        try:
            tool_class = self._registry.get(request.tool_name, request.tool_version)
        except ToolNotFoundError:
            self._audit_denial(
                request,
                SecurityEventType.UNKNOWN_TOOL_ATTEMPT,
                "unknown_tool",
                AuditCategory.AUTHORIZATION,
                AuditSeverity.WARNING,
            )
            raise
        if not tool_class.metadata.is_enabled:
            raise DisabledToolExecutionError(
                f"tool {request.tool_name!r} version "
                f"{request.tool_version!r} is disabled"
            )

        if self._role_policy_service is not None:
            try:
                role_decision = self._role_policy_service.evaluate(
                    request.context.principal_role, tool_class.metadata
                )
            except RolePolicyError as error:
                self._audit_denial(
                    request,
                    (
                        SecurityEventType.INVALID_ROLE_ESCALATION
                        if error.code.value == "unknown_role"
                        else SecurityEventType.POLICY_EVALUATION_FAILED
                    ),
                    error.code.value,
                    AuditCategory.SECURITY,
                    AuditSeverity.ERROR,
                    tool_class.metadata,
                )
                return ToolResult(
                    status=ToolStatus.FAILURE,
                    error=ToolError(
                        error_code=error.code.value,
                        public_message=error.public_message,
                    ),
                )
            if not role_decision.allowed:
                self._audit_denial(
                    request,
                    SecurityEventType.ROLE_POLICY_DENIED,
                    role_decision.failure_code.value,
                    AuditCategory.AUTHORIZATION,
                    AuditSeverity.WARNING,
                    tool_class.metadata,
                )
                return ToolResult(
                    status=ToolStatus.FAILURE,
                    error=ToolError(
                        error_code=role_decision.failure_code.value,
                        public_message=role_decision.public_message,
                    ),
                )

        if self._tool_authorization_service is not None:
            try:
                tool_decision = self._tool_authorization_service.authorize_tool(
                    request.context.principal_role,
                    request.tool_name,
                    request.tool_version,
                )
            except ToolAuthorizationPolicyError as error:
                self._audit_denial(
                    request,
                    (
                        SecurityEventType.UNKNOWN_TOOL_ATTEMPT
                        if error.code.value == "unknown_tool"
                        else SecurityEventType.POLICY_EVALUATION_FAILED
                    ),
                    error.code.value,
                    AuditCategory.AUTHORIZATION,
                    AuditSeverity.ERROR,
                    tool_class.metadata,
                )
                return ToolResult(
                    status=ToolStatus.FAILURE,
                    error=ToolError(
                        error_code=error.code.value,
                        public_message=error.public_message,
                    ),
                )
            if not tool_decision.allowed:
                self._audit_denial(
                    request,
                    SecurityEventType.TOOL_AUTHORIZATION_DENIED,
                    tool_decision.failure_code.value,
                    AuditCategory.AUTHORIZATION,
                    AuditSeverity.WARNING,
                    tool_class.metadata,
                )
                return ToolResult(
                    status=ToolStatus.FAILURE,
                    error=ToolError(
                        error_code=tool_decision.failure_code.value,
                        public_message=tool_decision.public_message,
                    ),
                )

        if self._authorization_service is not None:
            try:
                decision = self._authorization_service.authorize(
                    request, tool_class.metadata
                )
            except AuthorizationError as error:
                self._audit_denial(
                    request,
                    SecurityEventType.AUTHORIZATION_UNAVAILABLE,
                    error.code.value,
                    AuditCategory.SYSTEM,
                    AuditSeverity.ERROR,
                    tool_class.metadata,
                )
                return ToolResult(
                    status=ToolStatus.FAILURE,
                    error=ToolError(
                        error_code=error.code.value,
                        public_message=error.public_message,
                    ),
                )
            if not decision.allowed:
                self._audit_denial(
                    request,
                    (
                        SecurityEventType.INVALID_CUSTOMER_IMPERSONATION
                        if decision.failure_code.value
                        == "resource_ownership_mismatch"
                        else SecurityEventType.OWNERSHIP_DENIED
                    ),
                    decision.failure_code.value,
                    AuditCategory.AUTHORIZATION,
                    AuditSeverity.WARNING,
                    tool_class.metadata,
                )
                public_code = decision.failure_code.value
                public_message = decision.public_message
                if decision.failure_code.value in {
                    "resource_ownership_mismatch",
                    "unauthorized_resource",
                    "resource_not_found",
                }:
                    public_code = "resource_not_found"
                    public_message = "The requested resource was not found."
                return ToolResult(
                    status=ToolStatus.FAILURE,
                    error=ToolError(
                        error_code=public_code,
                        public_message=public_message,
                    ),
                )

        try:
            input_model = tool_class.input_schema.model_validate(
                json_copy(request.arguments)
            )
        except ValidationError as error:
            raise ToolInputRehydrationError(
                f"validated input for tool {request.tool_name!r} "
                "could not be rehydrated"
            ) from error

        return self._executor.execute(
            request.tool_name,
            request.tool_version,
            request.context,
            input_model,
        )

    def _audit_denial(
        self,
        request: ToolExecutionRequest,
        event_type: SecurityEventType,
        reason: str,
        category: AuditCategory,
        severity: AuditSeverity,
        metadata=None,
    ) -> None:
        self._security_audit.record(
            event_type,
            severity=severity,
            result=AuditResult.FAILURE,
            category=category,
            role=request.context.principal_role,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            capabilities=(
                tuple(item.value for item in metadata.grounding_capabilities)
                if metadata is not None
                else ()
            ),
            correlation_id=request.context.trace_id,
            request_id=request.context.execution_id,
            customer_id=request.context.customer_id,
            session_id=request.context.conversation_id,
            failure_reason_code=reason,
        )
