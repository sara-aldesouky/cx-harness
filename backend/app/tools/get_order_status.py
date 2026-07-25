"""Customer-facing, read-only order-status business tool."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.database.repositories import OrderRepository
from app.database.session import get_session_factory
from app.tools.context import ExecutionContext
from app.tools.contracts import (
    BaseTool,
    GroundingCapability,
    ToolCategory,
    ToolMetadata,
)
from app.tools.result import ToolError, ToolResult, ToolStatus


class GetOrderStatusInput(BaseModel):
    """Model-requested internal UUID or customer-facing order number."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: Union[UUID, str]

    @field_validator("order_id")
    @classmethod
    def validate_customer_identifier(
        cls, value: Union[UUID, str]
    ) -> Union[UUID, str]:
        if isinstance(value, UUID):
            return value
        normalized = value.strip().upper()
        if not re.fullmatch(
            r"(?:ORD-[0-9]{5,}|CX-[A-Z0-9]+(?:-[A-Z0-9]+)+)", normalized
        ):
            raise ValueError("order_id must be a UUID or customer-facing order number")
        return normalized


class GetOrderStatusOutput(BaseModel):
    """Customer-safe status information without internal identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    status: str
    payment_status: str
    estimated_delivery: Optional[datetime] = None
    created_at: datetime


class GetOrderStatusTool(BaseTool[GetOrderStatusInput, GetOrderStatusOutput]):
    """Look up an authenticated customer's order without changing data."""

    metadata = ToolMetadata(
        name="get_order_status",
        version="1.0.0",
        description="Return customer-safe status information for an owned order.",
        category=ToolCategory.ORDER,
        supported_use_cases=("order_status", "delivery_tracking"),
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
    input_schema = GetOrderStatusInput
    output_schema = GetOrderStatusOutput

    def execute(
        self,
        context: ExecutionContext,
        input_model: GetOrderStatusInput,
    ) -> ToolResult[GetOrderStatusOutput]:
        """Return status when the trusted customer owns the requested order."""

        if context.customer_id is None:
            return self._failure(
                "customer_identity_required",
                "Customer identity is required to look up an order.",
            )

        with get_session_factory()() as session:
            repository = OrderRepository(session)
            if isinstance(input_model.order_id, UUID):
                order = repository.get_by_id(input_model.order_id)
            else:
                order = repository.get_by_order_number(input_model.order_id)

        if order is None:
            return self._failure(
                "order_not_found",
                "The requested order could not be found.",
            )
        if order.customer_id != context.customer_id:
            return self._failure(
                "order_access_denied",
                "You do not have access to the requested order.",
            )

        return ToolResult[GetOrderStatusOutput](
            status=ToolStatus.SUCCESS,
            data=GetOrderStatusOutput(
                order_number=order.order_number,
                status=order.status,
                payment_status=order.payment_status,
                estimated_delivery=order.estimated_delivery_time,
                created_at=order.created_at,
            ),
        )

    @staticmethod
    def _failure(
        error_code: str,
        public_message: str,
    ) -> ToolResult[GetOrderStatusOutput]:
        return ToolResult[GetOrderStatusOutput](
            status=ToolStatus.FAILURE,
            error=ToolError(
                error_code=error_code,
                public_message=public_message,
            ),
        )
