"""Provider-independent, read-only Orders business capabilities."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.repositories import (
    CustomerRepository,
    OrderItemRepository,
    OrderRepository,
)
from app.database.session import get_session_factory
from app.tools.context import ExecutionContext
from app.tools.contracts import (
    BaseTool,
    GroundingCapability,
    ToolCategory,
    ToolMetadata,
)
from app.tools.result import ToolError, ToolResult, ToolStatus


class PaginationInput(BaseModel):
    """Validated deterministic pagination for customer-owned collections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


class OrderNumberInput(BaseModel):
    """One customer-facing order number; internal UUIDs are not required."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str = Field(min_length=1)

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(
            r"(?:ORD-[0-9]{5,}|CX-[A-Z0-9]+(?:-[A-Z0-9]+)+)", normalized
        ):
            raise ValueError("order_number is not a supported customer identifier")
        return normalized


class OrderItemsInput(OrderNumberInput):
    """Owned order number with bounded item pagination."""

    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class OrderSummary(BaseModel):
    """Customer-safe order list projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str = Field(min_length=1)
    status: str = Field(min_length=1)
    payment_status: str = Field(min_length=1)
    total_amount: Decimal = Field(ge=0)
    estimated_delivery: Optional[datetime] = None
    created_at: datetime


class OrderCollectionOutput(BaseModel):
    """Deterministically paginated order collection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    orders: tuple[OrderSummary, ...]
    total: int = Field(ge=0)
    limit: int
    offset: int


class OrderDetailsOutput(OrderSummary):
    """Detailed owned-order projection without address or internal IDs."""

    updated_at: datetime
    item_count: int = Field(ge=0)


class OrderItemOutput(BaseModel):
    """Customer-safe ordered item projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_name: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    line_total: Decimal = Field(ge=0)
    item_status: str = Field(min_length=1)


class OrderItemsOutput(BaseModel):
    """Paginated items for one verified customer-owned order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str = Field(min_length=1)
    items: tuple[OrderItemOutput, ...]
    total: int = Field(ge=0)
    limit: int
    offset: int


class ListCurrentOrdersTool(BaseTool[PaginationInput, OrderCollectionOutput]):
    """List the trusted customer's non-terminal orders."""

    metadata = ToolMetadata(
        name="list_current_orders",
        version="1.0.0",
        description="List current non-terminal orders for the authenticated customer.",
        category=ToolCategory.ORDER,
        supported_use_cases=("current_orders", "active_order_list"),
        grounding_capabilities=(GroundingCapability.ORDER,),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=False,
        is_read_only=True,
    )
    input_schema = PaginationInput
    output_schema = OrderCollectionOutput

    def execute(
        self, context: ExecutionContext, input_model: PaginationInput
    ) -> ToolResult[OrderCollectionOutput]:
        return _list_orders(context, input_model, historical=False)


class ListOrderHistoryTool(BaseTool[PaginationInput, OrderCollectionOutput]):
    """List the trusted customer's delivered or cancelled orders."""

    metadata = ToolMetadata(
        name="list_order_history",
        version="1.0.0",
        description="List delivered or cancelled orders for the authenticated customer.",
        category=ToolCategory.ORDER,
        supported_use_cases=("order_history", "past_orders"),
        grounding_capabilities=(GroundingCapability.ORDER,),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=False,
        is_read_only=True,
    )
    input_schema = PaginationInput
    output_schema = OrderCollectionOutput

    def execute(
        self, context: ExecutionContext, input_model: PaginationInput
    ) -> ToolResult[OrderCollectionOutput]:
        return _list_orders(context, input_model, historical=True)


class GetOrderDetailsTool(BaseTool[OrderNumberInput, OrderDetailsOutput]):
    """Retrieve one verified owned order without exposing its address or UUID."""

    metadata = ToolMetadata(
        name="get_order_details",
        version="1.0.0",
        description="Return customer-safe details for one owned order.",
        category=ToolCategory.ORDER,
        supported_use_cases=("order_details", "order_summary"),
        grounding_capabilities=(
            GroundingCapability.ORDER,
            GroundingCapability.DELIVERY,
            GroundingCapability.PAYMENT,
        ),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=False,
        is_read_only=True,
    )
    input_schema = OrderNumberInput
    output_schema = OrderDetailsOutput

    def execute(
        self, context: ExecutionContext, input_model: OrderNumberInput
    ) -> ToolResult[OrderDetailsOutput]:
        if context.customer_id is None:
            return _identity_failure()
        with get_session_factory()() as session:
            orders = OrderRepository(session)
            order = orders.get_by_order_number(input_model.order_number)
            if order is None or order.customer_id != context.customer_id:
                return _order_failure()
            item_count = OrderItemRepository(session).count(order_id=order.id)
        return ToolResult[OrderDetailsOutput](
            status=ToolStatus.SUCCESS,
            data=OrderDetailsOutput(
                **_order_summary(order).model_dump(),
                updated_at=order.updated_at,
                item_count=item_count,
            ),
        )


class GetOrderItemsTool(BaseTool[OrderItemsInput, OrderItemsOutput]):
    """Retrieve paginated item projections for one verified owned order."""

    metadata = ToolMetadata(
        name="get_order_items",
        version="1.0.0",
        description="Return customer-safe items for one owned order.",
        category=ToolCategory.ORDER,
        supported_use_cases=("order_items", "item_status"),
        grounding_capabilities=(GroundingCapability.ORDER,),
        requires_customer_identity=True,
        requires_order_ownership=True,
        requires_policy_check=False,
        is_read_only=True,
    )
    input_schema = OrderItemsInput
    output_schema = OrderItemsOutput

    def execute(
        self, context: ExecutionContext, input_model: OrderItemsInput
    ) -> ToolResult[OrderItemsOutput]:
        if context.customer_id is None:
            return _identity_failure()
        with get_session_factory()() as session:
            order = OrderRepository(session).get_by_order_number(
                input_model.order_number
            )
            if order is None or order.customer_id != context.customer_id:
                return _order_failure()
            repository = OrderItemRepository(session)
            items = repository.list_by_order_id(
                order.id, limit=input_model.limit, offset=input_model.offset
            )
            total = repository.count(order_id=order.id)
        return ToolResult[OrderItemsOutput](
            status=ToolStatus.SUCCESS,
            data=OrderItemsOutput(
                order_number=order.order_number,
                items=tuple(
                    OrderItemOutput(
                        product_name=item.product_name,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        line_total=item.unit_price * item.quantity,
                        item_status=item.item_status,
                    )
                    for item in items
                ),
                total=total,
                limit=input_model.limit,
                offset=input_model.offset,
            ),
        )


def _list_orders(
    context: ExecutionContext,
    input_model: PaginationInput,
    *,
    historical: bool,
) -> ToolResult[OrderCollectionOutput]:
    if context.customer_id is None:
        return _identity_failure()
    with get_session_factory()() as session:
        customers = CustomerRepository(session)
        if customers.get_by_id(context.customer_id) is None:
            return ToolResult(
                status=ToolStatus.FAILURE,
                error=ToolError(
                    error_code="customer_not_found",
                    public_message="The customer account could not be found.",
                ),
            )
        repository = OrderRepository(session)
        if historical:
            orders = repository.list_history_by_customer_id(
                context.customer_id, input_model.limit, input_model.offset
            )
            total = repository.count_history_by_customer_id(context.customer_id)
        else:
            orders = repository.list_current_by_customer_id(
                context.customer_id, input_model.limit, input_model.offset
            )
            total = repository.count_current_by_customer_id(context.customer_id)
    return ToolResult[OrderCollectionOutput](
        status=ToolStatus.SUCCESS,
        data=OrderCollectionOutput(
            orders=tuple(_order_summary(order) for order in orders),
            total=total,
            limit=input_model.limit,
            offset=input_model.offset,
        ),
    )


def _order_summary(order) -> OrderSummary:  # type: ignore[no-untyped-def]
    return OrderSummary(
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        total_amount=order.total_amount,
        estimated_delivery=order.estimated_delivery_time,
        created_at=order.created_at,
    )


def _identity_failure() -> ToolResult:
    return ToolResult(
        status=ToolStatus.FAILURE,
        error=ToolError(
            error_code="customer_identity_required",
            public_message="Customer identity is required for order information.",
        ),
    )


def _order_failure() -> ToolResult:
    return ToolResult(
        status=ToolStatus.FAILURE,
        error=ToolError(
            error_code="order_not_found",
            public_message="The requested order could not be found.",
        ),
    )
