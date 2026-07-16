"""Read-only tool-call endpoints."""

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import ToolCallRepository
from app.schemas.common import PaginatedResponse
from app.schemas.tool_call import ToolCallDetail, ToolCallSummary


router = APIRouter(prefix="/tool-calls", tags=["Tool Calls"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get(
    "", response_model=PaginatedResponse[ToolCallSummary], summary="List tool calls"
)
def list_tool_calls(
    session: SessionDependency,
    model_run_id: Optional[UUID] = None,
    tool_name: Optional[str] = None,
    status: Optional[str] = None,
    success: Optional[bool] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[ToolCallSummary]:
    repository = ToolCallRepository(session)
    filters = {
        "model_run_id": model_run_id,
        "tool_name": tool_name,
        "status": status,
        "success": success,
    }
    return PaginatedResponse(
        items=repository.list_tool_calls(limit, offset, **filters),
        total=repository.count_tool_calls(**filters),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{tool_call_id}",
    response_model=ToolCallDetail,
    summary="Get tool-call details",
)
def get_tool_call(tool_call_id: UUID, session: SessionDependency) -> ToolCallDetail:
    tool_call = ToolCallRepository(session).get_by_id(tool_call_id)
    if tool_call is None:
        raise HTTPException(status_code=404, detail="Tool call not found")
    return tool_call
