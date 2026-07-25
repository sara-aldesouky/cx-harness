"""Provider-independent, read-only Payment business capabilities."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.database.repositories import PaymentRepository
from app.database.session import get_session_factory
from app.tools.context import ExecutionContext
from app.tools.contracts import (
    BaseTool,
    GroundingCapability,
    ToolCategory,
    ToolMetadata,
)
from app.tools.order_capabilities import OrderNumberInput
from app.tools.result import ToolError, ToolResult, ToolStatus


class PaymentHistoryInput(OrderNumberInput):
    """Owned order number with bounded payment-event pagination."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class PaymentStatusOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    status: str
    updated_at: datetime


class PaymentMethodOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    method: str


class PaymentSummaryOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    status: str
    method: Optional[str] = None
    amount: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PaymentEventOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str
    description: str
    occurred_at: datetime


class LatestPaymentEventOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    event: PaymentEventOutput


class PaymentHistoryOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    events: tuple[PaymentEventOutput, ...]
    total: int = Field(ge=0)
    limit: int
    offset: int


def _metadata(
    name: str,
    description: str,
    use_cases: tuple[str, ...],
    *,
    includes_refund_state: bool = True,
) -> ToolMetadata:
    capabilities = (
        GroundingCapability.ORDER,
        GroundingCapability.PAYMENT,
    )
    if includes_refund_state:
        capabilities += (GroundingCapability.REFUND,)
    return ToolMetadata(
        name=name,
        version="1.0.0",
        description=description,
        category=ToolCategory.PAYMENT,
        supported_use_cases=use_cases,
        grounding_capabilities=capabilities,
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=False,
        is_read_only=True,
    )


class GetPaymentStatusTool(BaseTool[OrderNumberInput, PaymentStatusOutput]):
    metadata = _metadata(
        "get_payment_status",
        "Return the latest payment state for an owned order.",
        ("payment_status", "refund_status"),
    )
    input_schema = OrderNumberInput
    output_schema = PaymentStatusOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        payment = _owned_payment(context, input_model.order_number)
        if isinstance(payment, ToolResult):
            return payment
        if payment.status == "pending":
            return _failure(
                "payment_pending", "The payment is still pending."
            )
        if payment.status == "failed":
            return _failure(
                "payment_failed",
                payment.failure_reason_public or "The payment was not successful.",
            )
        return ToolResult[PaymentStatusOutput](
            status=ToolStatus.SUCCESS,
            data=PaymentStatusOutput(
                order_number=payment.order.order_number,
                status=payment.status,
                updated_at=payment.updated_at,
            ),
        )


class GetPaymentMethodTool(BaseTool[OrderNumberInput, PaymentMethodOutput]):
    metadata = _metadata(
        "get_payment_method",
        "Return the customer-safe payment method type for an owned order.",
        ("payment_method",),
        includes_refund_state=False,
    )
    input_schema = OrderNumberInput
    output_schema = PaymentMethodOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        payment = _owned_payment(context, input_model.order_number)
        if isinstance(payment, ToolResult):
            return payment
        if payment.method_type is None:
            return _failure(
                "payment_method_unavailable",
                "The payment method is not currently available.",
            )
        return ToolResult[PaymentMethodOutput](
            status=ToolStatus.SUCCESS,
            data=PaymentMethodOutput(
                order_number=payment.order.order_number,
                method=payment.method_type,
            ),
        )


class GetPaymentSummaryTool(BaseTool[OrderNumberInput, PaymentSummaryOutput]):
    metadata = _metadata(
        "get_payment_summary",
        "Return a customer-safe summary of the latest payment attempt.",
        ("payment_summary", "payment_failure_reason", "refund_status"),
    )
    input_schema = OrderNumberInput
    output_schema = PaymentSummaryOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        payment = _owned_payment(context, input_model.order_number)
        if isinstance(payment, ToolResult):
            return payment
        return ToolResult[PaymentSummaryOutput](
            status=ToolStatus.SUCCESS,
            data=PaymentSummaryOutput(
                order_number=payment.order.order_number,
                status=payment.status,
                method=payment.method_type,
                amount=payment.amount,
                currency=payment.currency,
                failure_reason=payment.failure_reason_public,
                created_at=payment.created_at,
                updated_at=payment.updated_at,
            ),
        )


class GetLatestPaymentEventTool(
    BaseTool[OrderNumberInput, LatestPaymentEventOutput]
):
    metadata = _metadata(
        "get_latest_payment_event",
        "Return the latest customer-visible payment event for an owned order.",
        ("latest_payment_event", "latest_refund_event"),
    )
    input_schema = OrderNumberInput
    output_schema = LatestPaymentEventOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        payment = _owned_payment(context, input_model.order_number)
        if isinstance(payment, ToolResult):
            return payment
        with get_session_factory()() as session:
            event = PaymentRepository(session).get_latest_event_for_order(
                input_model.order_number, context.customer_id
            )
        if event is None:
            return _failure(
                "payment_history_empty", "No payment events are available yet."
            )
        return ToolResult[LatestPaymentEventOutput](
            status=ToolStatus.SUCCESS,
            data=LatestPaymentEventOutput(
                order_number=payment.order.order_number,
                event=_event_output(event),
            ),
        )


class GetPaymentHistoryTool(BaseTool[PaymentHistoryInput, PaymentHistoryOutput]):
    metadata = _metadata(
        "get_payment_history",
        "Return customer-visible payment events for an owned order.",
        ("payment_history", "refund_history"),
    )
    input_schema = PaymentHistoryInput
    output_schema = PaymentHistoryOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        payment = _owned_payment(context, input_model.order_number)
        if isinstance(payment, ToolResult):
            return payment
        with get_session_factory()() as session:
            repository = PaymentRepository(session)
            events = repository.list_events_for_order(
                input_model.order_number,
                context.customer_id,
                input_model.limit,
                input_model.offset,
            )
            total = repository.count_events_for_order(
                input_model.order_number, context.customer_id
            )
        if total == 0:
            return _failure(
                "payment_history_empty", "No payment events are available yet."
            )
        return ToolResult[PaymentHistoryOutput](
            status=ToolStatus.SUCCESS,
            data=PaymentHistoryOutput(
                order_number=payment.order.order_number,
                events=tuple(_event_output(event) for event in events),
                total=total,
                limit=input_model.limit,
                offset=input_model.offset,
            ),
        )


def _owned_payment(context: ExecutionContext, order_number: str):  # type: ignore[no-untyped-def]
    if context.customer_id is None:
        return _failure(
            "customer_identity_required",
            "Customer identity is required for payment information.",
        )
    with get_session_factory()() as session:
        payment = PaymentRepository(session).get_latest_owned_by_order_number(
            order_number, context.customer_id
        )
    if payment is None:
        return _failure(
            "payment_not_found", "Payment information could not be found."
        )
    return payment


def _event_output(event) -> PaymentEventOutput:  # type: ignore[no-untyped-def]
    return PaymentEventOutput(
        event_type=event.event_type,
        description=event.public_description,
        occurred_at=event.occurred_at,
    )


def _failure(code: str, message: str) -> ToolResult:
    return ToolResult(
        status=ToolStatus.FAILURE,
        error=ToolError(error_code=code, public_message=message),
    )
