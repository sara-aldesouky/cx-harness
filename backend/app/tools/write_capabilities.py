"""Provider-neutral adapters exposing approved Stage 12 write operations."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, sessionmaker

from app.database.session import get_session_factory
from app.security_audit import security_audit_recorder
from app.tools.context import ExecutionContext
from app.tools.contracts import (
    BaseTool,
    GroundingCapability,
    ToolCategory,
    ToolMetadata,
)
from app.tools.result import ToolError, ToolResult, ToolStatus
from app.tools.security_approval import current_tool_execution_approval
from app.write_operations import (
    BaseWriteOperation,
    CancelOrderInput,
    CancelOrderOperation,
    CreateSupportTicketInput,
    CreateSupportTicketOperation,
    InitiateRefundInput,
    InitiateRefundOperation,
    SQLAlchemyAddressUpdateReader,
    SQLAlchemyAddressUpdateStore,
    SQLAlchemyOrderCancellationReader,
    SQLAlchemyOrderCancellationStore,
    SQLAlchemyRefundInitiationReader,
    SQLAlchemyRefundInitiationStore,
    SQLAlchemySupportTicketReader,
    SQLAlchemySupportTicketStore,
    SQLAlchemyTransactionManager,
    UpdateDeliveryAddressInput,
    UpdateDeliveryAddressOperation,
    WriteAuditEvent,
    WriteExecutionContext,
    WriteFrameworkExecutor,
    WriteSecurityEnvelope,
    WriteStatus,
)


logger = logging.getLogger("app.write_audit")


class WriteToolOutput(BaseModel):
    """Customer-safe deterministic write outcome for model continuation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: str
    operation_status: str
    result_code: str
    message: str
    order_reference: Optional[str] = None
    ticket_reference: Optional[str] = None
    business_change_applied: bool
    idempotent_no_op: bool
    retryable: bool = False


class LoggingWriteAuditObserver:
    """Emit the existing Stage 12 event contract with pseudonymous IDs."""

    def record(self, event: WriteAuditEvent) -> None:
        payload = {
            "operation_name": event.operation_name,
            "operation_version": event.operation_version,
            "timestamp": event.timestamp.isoformat(),
            "request_id": security_audit_recorder.pseudonymize(event.request_id),
            "correlation_id": security_audit_recorder.pseudonymize(
                event.correlation_id
            ),
            "resource_reference": event.resource_reference,
            "status": event.status.value,
            "business_change_applied": event.business_change_applied,
            "failure_phase": (
                event.failure_phase.value if event.failure_phase else None
            ),
            "failure_code": event.failure_code,
        }
        logger.info("write_audit %s", json.dumps(payload, sort_keys=True))


class _WriteToolAdapterMixin:
    """Thin bridge from BaseTool execution to one BaseWriteOperation."""

    def __init__(
        self,
        *,
        session_factory: Optional[sessionmaker[Session]] = None,
        audit_observer: Any = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        selected_factory = session_factory or get_session_factory()
        if not callable(selected_factory):
            raise TypeError("session_factory must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._session_factory = selected_factory
        self._audit_observer = audit_observer or LoggingWriteAuditObserver()
        if not callable(getattr(self._audit_observer, "record", None)):
            raise TypeError("audit_observer must provide record()")
        self._clock = clock

    def execute(
        self, context: ExecutionContext, input_model: BaseModel
    ) -> ToolResult[WriteToolOutput]:
        approval = current_tool_execution_approval()
        if approval is None or not approval.fully_authorized:
            return _failure(
                "write_security_not_approved",
                "The requested action is not authorized.",
            )
        if context.customer_id is None:
            return _failure(
                "customer_identity_required",
                "Customer identity is required for this action.",
            )
        try:
            operation = self._build_operation()
            write_context = WriteExecutionContext(
                execution_context=context,
                security=WriteSecurityEnvelope(
                    authenticated=approval.authenticated,
                    role_policy_allowed=approval.role_policy_allowed,
                    tool_authorized=approval.tool_authorized,
                    ownership_authorized=approval.ownership_authorized,
                ),
                request_id=context.execution_id,
                correlation_id=context.trace_id,
                requested_at=self._clock(),
            )
            result = WriteFrameworkExecutor(
                SQLAlchemyTransactionManager(self._session_factory),
                self._audit_observer,
            ).execute(operation, write_context, input_model)
        except Exception:
            return _failure(
                "write_adapter_unavailable",
                "The requested action is temporarily unavailable.",
            )
        if result.status is not WriteStatus.SUCCESS or result.outcome is None:
            assert result.error is not None
            return _failure(result.error.error_code, result.error.public_message)

        outcome = result.outcome
        changed = operation.business_change_applied(outcome)
        return ToolResult[WriteToolOutput](
            status=ToolStatus.SUCCESS,
            data=WriteToolOutput(
                operation=operation.name,
                operation_status=_safe_status(outcome),
                result_code=(
                    f"{operation.name}_completed"
                    if changed
                    else f"{operation.name}_no_change"
                ),
                message=result.message,
                order_reference=getattr(outcome, "order_number", None),
                ticket_reference=getattr(outcome, "ticket_reference", None),
                business_change_applied=changed,
                idempotent_no_op=not changed,
            ),
        )

    def _build_operation(self) -> BaseWriteOperation:
        raise NotImplementedError


class CancelOrderTool(
    _WriteToolAdapterMixin, BaseTool[CancelOrderInput, WriteToolOutput]
):
    metadata = ToolMetadata(
        name="cancel_order",
        version="1.0.0",
        description="Cancel an eligible order owned by the authenticated customer.",
        category=ToolCategory.ORDER,
        supported_use_cases=("order_cancellation",),
        grounding_capabilities=(GroundingCapability.ORDER,),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=True,
        is_read_only=False,
    )
    input_schema = CancelOrderInput
    output_schema = WriteToolOutput

    def _build_operation(self) -> CancelOrderOperation:
        return CancelOrderOperation(
            SQLAlchemyOrderCancellationReader(self._session_factory),
            SQLAlchemyOrderCancellationStore,
            clock=self._clock,
        )


class UpdateDeliveryAddressTool(
    _WriteToolAdapterMixin, BaseTool[UpdateDeliveryAddressInput, WriteToolOutput]
):
    metadata = ToolMetadata(
        name="update_delivery_address",
        version="1.0.0",
        description="Update the delivery address for an eligible owned order.",
        category=ToolCategory.ORDER,
        supported_use_cases=("delivery_address_update",),
        grounding_capabilities=(
            GroundingCapability.ORDER,
            GroundingCapability.DELIVERY,
        ),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=True,
        is_read_only=False,
    )
    input_schema = UpdateDeliveryAddressInput
    output_schema = WriteToolOutput

    def _build_operation(self) -> UpdateDeliveryAddressOperation:
        return UpdateDeliveryAddressOperation(
            SQLAlchemyAddressUpdateReader(self._session_factory),
            SQLAlchemyAddressUpdateStore,
            clock=self._clock,
        )


class InitiateRefundTool(
    _WriteToolAdapterMixin, BaseTool[InitiateRefundInput, WriteToolOutput]
):
    metadata = ToolMetadata(
        name="initiate_refund",
        version="1.0.0",
        description="Submit an eligible refund request for an owned order.",
        category=ToolCategory.PAYMENT,
        supported_use_cases=("refund_initiation",),
        grounding_capabilities=(
            GroundingCapability.ORDER,
            GroundingCapability.PAYMENT,
            GroundingCapability.REFUND,
        ),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=True,
        is_read_only=False,
    )
    input_schema = InitiateRefundInput
    output_schema = WriteToolOutput

    def _build_operation(self) -> InitiateRefundOperation:
        return InitiateRefundOperation(
            SQLAlchemyRefundInitiationReader(self._session_factory),
            SQLAlchemyRefundInitiationStore,
            clock=self._clock,
        )


class CreateSupportTicketTool(
    _WriteToolAdapterMixin, BaseTool[CreateSupportTicketInput, WriteToolOutput]
):
    metadata = ToolMetadata(
        name="create_support_ticket",
        version="1.0.0",
        description="Create one support ticket for an unresolved customer issue.",
        category=ToolCategory.SUPPORT,
        supported_use_cases=("support_escalation", "missing_item_escalation"),
        grounding_capabilities=(GroundingCapability.SUPPORT,),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=True,
        is_read_only=False,
    )
    input_schema = CreateSupportTicketInput
    output_schema = WriteToolOutput

    def _build_operation(self) -> CreateSupportTicketOperation:
        return CreateSupportTicketOperation(
            SQLAlchemySupportTicketReader(self._session_factory),
            SQLAlchemySupportTicketStore,
            clock=self._clock,
        )


WRITE_TOOL_CLASSES = (
    CancelOrderTool,
    UpdateDeliveryAddressTool,
    InitiateRefundTool,
    CreateSupportTicketTool,
)


class WriteToolFactory:
    """Inject shared runtime dependencies into write adapters only."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        audit_observer: Any = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory
        self._audit_observer = audit_observer or LoggingWriteAuditObserver()
        if not callable(getattr(self._audit_observer, "record", None)):
            raise TypeError("audit_observer must provide record()")

    def __call__(self, tool_class: type) -> BaseTool:
        if tool_class in WRITE_TOOL_CLASSES:
            return tool_class(
                session_factory=self._session_factory,
                audit_observer=self._audit_observer,
            )
        return tool_class()


def _failure(code: str, message: str) -> ToolResult[WriteToolOutput]:
    return ToolResult[WriteToolOutput](
        status=ToolStatus.FAILURE,
        error=ToolError(error_code=code, public_message=message),
    )


def _safe_status(outcome: BaseModel) -> str:
    for attribute in ("status", "refund_status"):
        value = getattr(outcome, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "completed"
