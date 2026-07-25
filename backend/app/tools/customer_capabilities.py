"""Provider-independent, read-only Customer business capabilities."""

from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.database.repositories import CustomerRepository, OrderRepository
from app.database.session import get_session_factory
from app.tools.context import ExecutionContext
from app.tools.contracts import (
    BaseTool,
    GroundingCapability,
    ToolCategory,
    ToolMetadata,
)
from app.tools.result import ToolError, ToolResult, ToolStatus


class CustomerProfileInput(BaseModel):
    """Explicit profile intent; customer identity remains trusted context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: Literal["profile"]


class CustomerSummaryInput(BaseModel):
    """Explicit summary intent; customer identity remains trusted context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: Literal["summary"]


class CustomerProfileOutput(BaseModel):
    """Minimal customer-safe profile with direct contact details excluded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    display_name: str = Field(min_length=1)
    preferred_language: str = Field(min_length=1)
    account_status: Literal["active", "inactive"]
    member_since: datetime


class CustomerSummaryOutput(BaseModel):
    """Customer-safe commerce summary derived from PostgreSQL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    display_name: str = Field(min_length=1)
    preferred_language: str = Field(min_length=1)
    current_order_count: int = Field(ge=0)
    completed_order_count: int = Field(ge=0)
    total_order_count: int = Field(ge=0)


class GetCustomerProfileTool(
    BaseTool[CustomerProfileInput, CustomerProfileOutput]
):
    """Return the trusted customer's non-sensitive profile projection."""

    metadata = ToolMetadata(
        name="get_customer_profile",
        version="1.0.0",
        description=(
            "Return a non-sensitive profile for the authenticated customer."
        ),
        category=ToolCategory.CUSTOMER,
        supported_use_cases=("customer_profile", "preferred_language"),
        grounding_capabilities=(GroundingCapability.CUSTOMER,),
        requires_customer_identity=True,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
    )
    input_schema = CustomerProfileInput
    output_schema = CustomerProfileOutput

    def execute(
        self,
        context: ExecutionContext,
        input_model: CustomerProfileInput,
    ) -> ToolResult[CustomerProfileOutput]:
        del input_model
        if context.customer_id is None:
            return _failure(
                "customer_identity_required",
                "Customer identity is required to retrieve a profile.",
            )
        with get_session_factory()() as session:
            customer = CustomerRepository(session).get_by_id(context.customer_id)
        if customer is None:
            return _failure(
                "customer_not_found",
                "The customer profile could not be found.",
            )
        return ToolResult[CustomerProfileOutput](
            status=ToolStatus.SUCCESS,
            data=CustomerProfileOutput(
                display_name=f"{customer.first_name} {customer.last_name}".strip(),
                preferred_language=customer.preferred_language,
                account_status="active" if customer.is_active else "inactive",
                member_since=customer.created_at,
            ),
        )


class GetCustomerSummaryTool(
    BaseTool[CustomerSummaryInput, CustomerSummaryOutput]
):
    """Return safe customer identity and aggregate order counts."""

    metadata = ToolMetadata(
        name="get_customer_summary",
        version="1.0.0",
        description=(
            "Return a safe customer summary with current and historical order counts."
        ),
        category=ToolCategory.CUSTOMER,
        supported_use_cases=("customer_summary", "order_count_summary"),
        grounding_capabilities=(
            GroundingCapability.CUSTOMER,
            GroundingCapability.ORDER,
        ),
        requires_customer_identity=True,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
    )
    input_schema = CustomerSummaryInput
    output_schema = CustomerSummaryOutput

    def execute(
        self,
        context: ExecutionContext,
        input_model: CustomerSummaryInput,
    ) -> ToolResult[CustomerSummaryOutput]:
        del input_model
        if context.customer_id is None:
            return _failure(
                "customer_identity_required",
                "Customer identity is required to retrieve a summary.",
            )
        with get_session_factory()() as session:
            customer = CustomerRepository(session).get_by_id(context.customer_id)
            if customer is None:
                return _failure(
                    "customer_not_found",
                    "The customer summary could not be found.",
                )
            orders = OrderRepository(session)
            current_count = orders.count_current_by_customer_id(context.customer_id)
            completed_count = orders.count_history_by_customer_id(
                context.customer_id
            )
            total_count = orders.count(customer_id=context.customer_id)
        return ToolResult[CustomerSummaryOutput](
            status=ToolStatus.SUCCESS,
            data=CustomerSummaryOutput(
                display_name=f"{customer.first_name} {customer.last_name}".strip(),
                preferred_language=customer.preferred_language,
                current_order_count=current_count,
                completed_order_count=completed_count,
                total_order_count=total_count,
            ),
        )


def _failure(code: str, message: str) -> ToolResult:
    return ToolResult(
        status=ToolStatus.FAILURE,
        error=ToolError(error_code=code, public_message=message),
    )
