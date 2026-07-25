"""Provider-independent, read-only Refund business capabilities."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.database.repositories import RefundRepository
from app.database.session import get_session_factory
from app.tools.context import ExecutionContext
from app.tools.contracts import BaseTool, GroundingCapability, ToolCategory, ToolMetadata
from app.tools.order_capabilities import OrderNumberInput
from app.tools.result import ToolError, ToolResult, ToolStatus


class RefundHistoryInput(OrderNumberInput):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RefundStatusOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_number: str
    status: str
    updated_at: datetime


class RefundSummaryOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_number: str
    status: str
    refund_type: str
    amount: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    reason: Optional[str] = None
    requested_at: datetime
    processed_at: Optional[datetime] = None


class RefundHistoryOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_number: str
    refunds: tuple[RefundSummaryOutput, ...]
    events: tuple[RefundEventOutput, ...]
    total: int = Field(ge=0)
    event_total: int = Field(ge=0)
    limit: int
    offset: int


class RefundEventOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_type: str
    description: str
    occurred_at: datetime


class LatestRefundEventOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_number: str
    event: RefundEventOutput


class RefundEligibilityOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order_number: str
    eligible: bool
    reason: str
    assessed_at: datetime


def _metadata(name: str, description: str, use_cases: tuple[str, ...]) -> ToolMetadata:
    return ToolMetadata(
        name=name, version="1.0.0", description=description,
        category=ToolCategory.PAYMENT, supported_use_cases=use_cases,
        grounding_capabilities=(
            GroundingCapability.ORDER,
            GroundingCapability.PAYMENT,
            GroundingCapability.REFUND,
        ),
        requires_customer_identity=True, requires_order_ownership=True,
        requires_policy_check=False, is_read_only=True,
    )


class GetRefundStatusTool(BaseTool[OrderNumberInput, RefundStatusOutput]):
    metadata = _metadata("get_refund_status", "Return the latest refund state for an owned order.", ("refund_status",))
    input_schema = OrderNumberInput
    output_schema = RefundStatusOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        refund = _owned_refund(context, input_model.order_number)
        if isinstance(refund, ToolResult): return refund
        if refund.status in {"pending", "processing"}:
            return _failure("refund_pending", "The refund is still being processed.")
        if refund.status == "rejected":
            return _failure("refund_rejected", refund.public_reason or "The refund was not accepted.")
        return ToolResult[RefundStatusOutput](status=ToolStatus.SUCCESS, data=RefundStatusOutput(
            order_number=refund.payment.order.order_number, status=refund.status, updated_at=refund.updated_at
        ))


class GetRefundSummaryTool(BaseTool[OrderNumberInput, RefundSummaryOutput]):
    metadata = _metadata("get_refund_summary", "Return a customer-safe summary of the latest refund.", ("refund_summary", "refund_amount", "refund_processed_time"))
    input_schema = OrderNumberInput
    output_schema = RefundSummaryOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        refund = _owned_refund(context, input_model.order_number)
        if isinstance(refund, ToolResult): return refund
        if refund.amount is None:
            return _failure("refund_amount_unavailable", "The refund amount is not currently available.")
        return ToolResult[RefundSummaryOutput](status=ToolStatus.SUCCESS, data=_summary(refund))


class GetRefundHistoryTool(BaseTool[RefundHistoryInput, RefundHistoryOutput]):
    metadata = _metadata("get_refund_history", "Return refund history for an owned order.", ("refund_history", "multiple_refunds"))
    input_schema = RefundHistoryInput
    output_schema = RefundHistoryOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        if context.customer_id is None: return _identity_failure()
        with get_session_factory()() as session:
            repo = RefundRepository(session)
            refunds = repo.list_owned_by_order_number(input_model.order_number, context.customer_id, input_model.limit, input_model.offset)
            total = repo.count_owned_by_order_number(input_model.order_number, context.customer_id)
            events = repo.list_events_for_order(
                input_model.order_number,
                context.customer_id,
                input_model.limit,
                input_model.offset,
            )
            event_total = repo.count_events_for_order(
                input_model.order_number, context.customer_id
            )
        if total == 0: return _failure("refund_history_empty", "No refund history is available for this order.")
        if any(refund.amount is None for refund in refunds):
            return _failure("refund_amount_unavailable", "A refund amount is not currently available.")
        return ToolResult[RefundHistoryOutput](status=ToolStatus.SUCCESS, data=RefundHistoryOutput(
            order_number=input_model.order_number,
            refunds=tuple(_summary(refund) for refund in refunds), total=total,
            events=tuple(
                RefundEventOutput(
                    event_type=event.event_type,
                    description=event.public_description,
                    occurred_at=event.occurred_at,
                )
                for event in events
            ),
            event_total=event_total,
            limit=input_model.limit, offset=input_model.offset,
        ))


class GetLatestRefundEventTool(BaseTool[OrderNumberInput, LatestRefundEventOutput]):
    metadata = _metadata("get_latest_refund_event", "Return the latest customer-visible refund event.", ("latest_refund_event",))
    input_schema = OrderNumberInput
    output_schema = LatestRefundEventOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        if context.customer_id is None: return _identity_failure()
        with get_session_factory()() as session:
            event = RefundRepository(session).get_latest_event_for_order(input_model.order_number, context.customer_id)
        if event is None: return _failure("refund_history_empty", "No refund events are available for this order.")
        return ToolResult[LatestRefundEventOutput](status=ToolStatus.SUCCESS, data=LatestRefundEventOutput(
            order_number=input_model.order_number,
            event=RefundEventOutput(event_type=event.event_type, description=event.public_description, occurred_at=event.occurred_at),
        ))


class CheckRefundEligibilityTool(BaseTool[OrderNumberInput, RefundEligibilityOutput]):
    metadata = _metadata("check_refund_eligibility", "Return the stored business eligibility assessment for an owned order; this never approves or executes a refund.", ("refund_eligibility",))
    input_schema = OrderNumberInput
    output_schema = RefundEligibilityOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        if context.customer_id is None: return _identity_failure()
        with get_session_factory()() as session:
            assessment = RefundRepository(session).get_eligibility_for_order(input_model.order_number, context.customer_id)
        if assessment is None:
            return _failure("refund_not_eligible", "Refund eligibility is not currently available for this order.")
        if assessment.status != "eligible":
            return _failure("refund_not_eligible", assessment.public_reason)
        return ToolResult[RefundEligibilityOutput](status=ToolStatus.SUCCESS, data=RefundEligibilityOutput(
            order_number=assessment.order.order_number, eligible=True,
            reason=assessment.public_reason, assessed_at=assessment.assessed_at,
        ))


def _owned_refund(context: ExecutionContext, order_number: str):  # type: ignore[no-untyped-def]
    if context.customer_id is None: return _identity_failure()
    with get_session_factory()() as session:
        refund = RefundRepository(session).get_latest_owned_by_order_number(order_number, context.customer_id)
    if refund is None: return _failure("refund_not_found", "Refund information could not be found.")
    return refund


def _summary(refund):  # type: ignore[no-untyped-def]
    refund_type = "full" if refund.amount == refund.payment.amount else "partial"
    return RefundSummaryOutput(
        order_number=refund.payment.order.order_number, status=refund.status,
        refund_type=refund_type, amount=refund.amount, currency=refund.currency,
        reason=refund.public_reason, requested_at=refund.requested_at,
        processed_at=refund.processed_at,
    )


def _identity_failure() -> ToolResult:
    return _failure("customer_identity_required", "Customer identity is required for refund information.")


def _failure(code: str, message: str) -> ToolResult:
    return ToolResult(status=ToolStatus.FAILURE, error=ToolError(error_code=code, public_message=message))
