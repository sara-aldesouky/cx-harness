"""Minimal provider-independent orchestration for registered tools."""

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from typing import Optional

from pydantic import BaseModel

from app.database.repositories import ToolCallAuditRepository
from app.database.session import get_session_factory
from app.config.settings import settings
from app.tools.audit_payload import sanitize_audit_payload
from app.tools.context import ExecutionContext
from app.tools.registry import ToolRegistry
from app.tools.result import ToolResult, ToolStatus


class ToolExecutionContractError(TypeError):
    """Raised when an invocation violates a declared tool contract."""


class ToolExecutor:
    """Resolve and synchronously invoke registered tool classes.

    The executor owns orchestration, audit persistence, input-boundary
    validation, invocation, and result-contract verification. It does not own
    authentication, authorization, policy, providers, telemetry, retry
    behavior, or business logic.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        audit_repository: Optional[ToolCallAuditRepository] = None,
        audit_payload_max_bytes: Optional[int] = None,
    ) -> None:
        self._registry = registry
        self._audit_repository = (
            audit_repository
            if audit_repository is not None
            else ToolCallAuditRepository(get_session_factory())
        )
        self._audit_payload_max_bytes = (
            settings.audit_payload_max_bytes
            if audit_payload_max_bytes is None
            else audit_payload_max_bytes
        )
        if self._audit_payload_max_bytes <= 0:
            raise ValueError("audit_payload_max_bytes must be positive")

    def execute(
        self,
        name: str,
        version: str,
        context: ExecutionContext,
        input_model: BaseModel,
    ) -> ToolResult[BaseModel]:
        """Resolve, validate, invoke, and verify one registered tool."""

        tool_class = self._registry.get(name, version)

        if not isinstance(context, ExecutionContext):
            raise ToolExecutionContractError(
                "context must be an ExecutionContext instance"
            )
        if not isinstance(input_model, tool_class.input_schema):
            raise ToolExecutionContractError(
                f"input_model must be an instance of "
                f"{tool_class.input_schema.__name__}"
            )

        started_at = datetime.now(timezone.utc)
        sanitized_input = sanitize_audit_payload(
            input_model.model_dump(mode="json"), self._audit_payload_max_bytes
        )
        tool_call_id = self._audit_repository.create_running(
            context=context,
            tool_name=name,
            tool_version=version,
            input_json=sanitized_input.payload,
            input_truncated=sanitized_input.truncated,
            started_at=started_at,
        )
        started_monotonic = monotonic()
        try:
            tool = tool_class()
            result = tool.execute(context, input_model)
            if not isinstance(result, ToolResult):
                raise ToolExecutionContractError(
                    "tool execution must return a ToolResult instance"
                )
            if result.status is ToolStatus.SUCCESS and not isinstance(
                result.data, tool_class.output_schema
            ):
                raise ToolExecutionContractError(
                    f"successful tool data must be an instance of "
                    f"{tool_class.output_schema.__name__}"
                )
        except BaseException as execution_error:
            duration_ms = self._duration_ms(started_monotonic)
            try:
                self._audit_repository.finalize(
                    tool_call_id,
                    status="error",
                    success=False,
                    output_json=None,
                    output_truncated=False,
                    error_code=None,
                    exception_type=type(execution_error).__name__,
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                )
            except Exception as audit_error:
                raise execution_error from audit_error
            raise

        business_failure = result.status is ToolStatus.FAILURE
        sanitized_output = sanitize_audit_payload(
            result.model_dump(mode="json"), self._audit_payload_max_bytes
        )
        self._audit_repository.finalize(
            tool_call_id,
            status="failed" if business_failure else "completed",
            success=not business_failure,
            output_json=sanitized_output.payload,
            output_truncated=sanitized_output.truncated,
            error_code=(
                result.error.error_code
                if business_failure and result.error is not None
                else None
            ),
            exception_type=None,
            finished_at=datetime.now(timezone.utc),
            duration_ms=self._duration_ms(started_monotonic),
        )
        return result

    @staticmethod
    def _duration_ms(started_monotonic: float) -> int:
        """Calculate a non-negative elapsed duration using a monotonic clock."""

        return max(0, int((monotonic() - started_monotonic) * 1000))
