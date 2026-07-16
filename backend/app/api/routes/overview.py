"""Read-only dashboard overview endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import (
    ConversationRepository,
    CustomerRepository,
    EvaluationRepository,
    MessageRepository,
    ModelRunRepository,
    OrderItemRepository,
    OrderRepository,
    ToolCallRepository,
)


class OverviewResponse(BaseModel):
    customers: int = Field(ge=0)
    orders: int = Field(ge=0)
    order_items: int = Field(ge=0)
    conversations: int = Field(ge=0)
    messages: int = Field(ge=0)
    model_runs: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    evaluations: int = Field(ge=0)


router = APIRouter(tags=["Overview"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get("/overview", response_model=OverviewResponse, summary="Get database overview")
def get_overview(session: SessionDependency) -> OverviewResponse:
    return OverviewResponse(
        customers=CustomerRepository(session).count(),
        orders=OrderRepository(session).count_orders(),
        order_items=OrderItemRepository(session).count_items(),
        conversations=ConversationRepository(session).count_conversations(),
        messages=MessageRepository(session).count_messages(),
        model_runs=ModelRunRepository(session).count_model_runs(),
        tool_calls=ToolCallRepository(session).count_tool_calls(),
        evaluations=EvaluationRepository(session).count_evaluations(),
    )
