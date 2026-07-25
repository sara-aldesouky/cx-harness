"""Provider-independent, read-only Delivery business capabilities."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.database.repositories import DeliveryRepository
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


class DeliveryHistoryInput(OrderNumberInput):
    """Owned order number with bounded delivery-event pagination."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class DeliveryStatusOutput(BaseModel):
    """Customer-safe current delivery state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    status: str
    is_delayed: bool
    updated_at: datetime


class DeliveryEtaOutput(BaseModel):
    """Customer-safe estimated delivery timestamp."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    estimated_delivery: datetime


class DeliveryWindowOutput(BaseModel):
    """Customer-safe scheduled delivery window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    window_start: datetime
    window_end: datetime


class DeliveryEventOutput(BaseModel):
    """One customer-visible delivery update without internal identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str
    description: str
    occurred_at: datetime


class LatestDeliveryEventOutput(BaseModel):
    """Latest event for one customer-owned delivery."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    event: DeliveryEventOutput


class DeliveryHistoryOutput(BaseModel):
    """Deterministically paginated customer-visible delivery history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    events: tuple[DeliveryEventOutput, ...]
    total: int = Field(ge=0)
    limit: int
    offset: int


def _metadata(name: str, description: str, use_cases: tuple[str, ...]) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        version="1.0.0",
        description=description,
        category=ToolCategory.ORDER,
        supported_use_cases=use_cases,
        grounding_capabilities=(
            GroundingCapability.ORDER,
            GroundingCapability.DELIVERY,
        ),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=False,
        is_read_only=True,
    )


class GetDeliveryStatusTool(BaseTool[OrderNumberInput, DeliveryStatusOutput]):
    metadata = _metadata(
        "get_delivery_status",
        "Return the current delivery state for an owned order.",
        ("delivery_status", "delivery_delay"),
    )
    input_schema = OrderNumberInput
    output_schema = DeliveryStatusOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        delivery = _owned_delivery(context, input_model.order_number)
        if isinstance(delivery, ToolResult):
            return delivery
        return ToolResult[DeliveryStatusOutput](
            status=ToolStatus.SUCCESS,
            data=DeliveryStatusOutput(
                order_number=delivery.order.order_number,
                status=delivery.status,
                is_delayed=delivery.status == "delayed",
                updated_at=delivery.updated_at,
            ),
        )


class GetDeliveryEtaTool(BaseTool[OrderNumberInput, DeliveryEtaOutput]):
    metadata = _metadata(
        "get_delivery_eta",
        "Return the estimated arrival time for an owned order delivery.",
        ("delivery_eta", "arrival_time"),
    )
    input_schema = OrderNumberInput
    output_schema = DeliveryEtaOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        delivery = _owned_delivery(context, input_model.order_number)
        if isinstance(delivery, ToolResult):
            return delivery
        if delivery.status == "not_started":
            return _failure(
                "delivery_not_started", "Delivery has not started for this order."
            )
        if delivery.estimated_delivery_time is None:
            return _failure(
                "eta_unavailable",
                "An estimated delivery time is not currently available.",
            )
        return ToolResult[DeliveryEtaOutput](
            status=ToolStatus.SUCCESS,
            data=DeliveryEtaOutput(
                order_number=delivery.order.order_number,
                estimated_delivery=delivery.estimated_delivery_time,
            ),
        )


class GetDeliveryWindowTool(BaseTool[OrderNumberInput, DeliveryWindowOutput]):
    metadata = _metadata(
        "get_delivery_window",
        "Return the scheduled arrival window for an owned order delivery.",
        ("delivery_window", "scheduled_arrival"),
    )
    input_schema = OrderNumberInput
    output_schema = DeliveryWindowOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        delivery = _owned_delivery(context, input_model.order_number)
        if isinstance(delivery, ToolResult):
            return delivery
        if delivery.status == "not_started":
            return _failure(
                "delivery_not_started", "Delivery has not started for this order."
            )
        if delivery.window_start is None or delivery.window_end is None:
            return _failure(
                "delivery_window_unavailable",
                "A delivery window is not currently available.",
            )
        return ToolResult[DeliveryWindowOutput](
            status=ToolStatus.SUCCESS,
            data=DeliveryWindowOutput(
                order_number=delivery.order.order_number,
                window_start=delivery.window_start,
                window_end=delivery.window_end,
            ),
        )


class GetLatestDeliveryEventTool(
    BaseTool[OrderNumberInput, LatestDeliveryEventOutput]
):
    metadata = _metadata(
        "get_latest_delivery_event",
        "Return the latest customer-visible update for an owned delivery.",
        ("latest_delivery_event", "delivery_attempt"),
    )
    input_schema = OrderNumberInput
    output_schema = LatestDeliveryEventOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        delivery = _owned_delivery(context, input_model.order_number)
        if isinstance(delivery, ToolResult):
            return delivery
        if delivery.status == "not_started":
            return _failure(
                "delivery_not_started", "Delivery has not started for this order."
            )
        with get_session_factory()() as session:
            event = DeliveryRepository(session).get_latest_event(delivery.id)
        if event is None:
            return _failure(
                "delivery_history_empty", "No delivery updates are available yet."
            )
        return ToolResult[LatestDeliveryEventOutput](
            status=ToolStatus.SUCCESS,
            data=LatestDeliveryEventOutput(
                order_number=delivery.order.order_number,
                event=_event_output(event),
            ),
        )


class GetDeliveryHistoryTool(
    BaseTool[DeliveryHistoryInput, DeliveryHistoryOutput]
):
    metadata = _metadata(
        "get_delivery_history",
        "Return customer-visible event history for an owned delivery.",
        ("delivery_history", "delivery_attempt_history"),
    )
    input_schema = DeliveryHistoryInput
    output_schema = DeliveryHistoryOutput

    def execute(self, context, input_model):  # type: ignore[no-untyped-def]
        delivery = _owned_delivery(context, input_model.order_number)
        if isinstance(delivery, ToolResult):
            return delivery
        if delivery.status == "not_started":
            return _failure(
                "delivery_not_started", "Delivery has not started for this order."
            )
        with get_session_factory()() as session:
            repository = DeliveryRepository(session)
            events = repository.list_events(
                delivery.id, input_model.limit, input_model.offset
            )
            total = repository.count_events(delivery.id)
        if total == 0:
            return _failure(
                "delivery_history_empty", "No delivery updates are available yet."
            )
        return ToolResult[DeliveryHistoryOutput](
            status=ToolStatus.SUCCESS,
            data=DeliveryHistoryOutput(
                order_number=delivery.order.order_number,
                events=tuple(_event_output(event) for event in events),
                total=total,
                limit=input_model.limit,
                offset=input_model.offset,
            ),
        )


def _owned_delivery(context: ExecutionContext, order_number: str):  # type: ignore[no-untyped-def]
    if context.customer_id is None:
        return _failure(
            "customer_identity_required",
            "Customer identity is required for delivery information.",
        )
    with get_session_factory()() as session:
        delivery = DeliveryRepository(session).get_owned_by_order_number(
            order_number, context.customer_id
        )
    if delivery is None:
        return _failure(
            "delivery_not_found", "Delivery information could not be found."
        )
    return delivery


def _event_output(event) -> DeliveryEventOutput:  # type: ignore[no-untyped-def]
    return DeliveryEventOutput(
        event_type=event.event_type,
        description=event.public_description,
        occurred_at=event.occurred_at,
    )


def _failure(code: str, message: str) -> ToolResult:
    return ToolResult(
        status=ToolStatus.FAILURE,
        error=ToolError(error_code=code, public_message=message),
    )
