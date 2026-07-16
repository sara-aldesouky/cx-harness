"""Read-only model-run endpoints."""

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import (
    EvaluationRepository,
    ModelRunRepository,
    ToolCallRepository,
)
from app.schemas.common import PaginatedResponse
from app.schemas.evaluation import EvaluationSummary
from app.schemas.model_run import ModelRunDetail, ModelRunSummary
from app.schemas.tool_call import ToolCallSummary


router = APIRouter(prefix="/model-runs", tags=["Model Runs"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get(
    "", response_model=PaginatedResponse[ModelRunSummary], summary="List model runs"
)
def list_model_runs(
    session: SessionDependency,
    conversation_id: Optional[UUID] = None,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    status: Optional[str] = None,
    success: Optional[bool] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[ModelRunSummary]:
    repository = ModelRunRepository(session)
    filters = {
        "conversation_id": conversation_id,
        "provider": provider,
        "model_name": model_name,
        "status": status,
        "success": success,
    }
    return PaginatedResponse(
        items=repository.list_model_runs(limit, offset, **filters),
        total=repository.count_model_runs(**filters),
        limit=limit,
        offset=offset,
    )


def _require_model_run(model_run_id: UUID, session: Session) -> None:
    if ModelRunRepository(session).get_by_id(model_run_id) is None:
        raise HTTPException(status_code=404, detail="Model run not found")


@router.get(
    "/{model_run_id}/tool-calls",
    response_model=PaginatedResponse[ToolCallSummary],
    summary="List tool calls for a model run",
)
def get_model_run_tool_calls(
    model_run_id: UUID,
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[ToolCallSummary]:
    _require_model_run(model_run_id, session)
    repository = ToolCallRepository(session)
    return PaginatedResponse(
        items=repository.list_by_model_run(model_run_id, limit, offset),
        total=repository.count_tool_calls(model_run_id=model_run_id),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{model_run_id}/evaluations",
    response_model=PaginatedResponse[EvaluationSummary],
    summary="List evaluations for a model run",
)
def get_model_run_evaluations(
    model_run_id: UUID,
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[EvaluationSummary]:
    _require_model_run(model_run_id, session)
    repository = EvaluationRepository(session)
    return PaginatedResponse(
        items=repository.list_by_model_run(model_run_id, limit, offset),
        total=repository.count_evaluations(model_run_id=model_run_id),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{model_run_id}",
    response_model=ModelRunDetail,
    summary="Get model-run details",
)
def get_model_run(model_run_id: UUID, session: SessionDependency) -> ModelRunDetail:
    model_run = ModelRunRepository(session).get_with_details(model_run_id)
    if model_run is None:
        raise HTTPException(status_code=404, detail="Model run not found")
    return model_run
