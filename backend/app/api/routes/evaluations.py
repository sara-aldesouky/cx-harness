"""Read-only evaluation endpoints."""

from decimal import Decimal
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import EvaluationRepository
from app.schemas.common import PaginatedResponse
from app.schemas.evaluation import EvaluationDetail, EvaluationSummary


router = APIRouter(prefix="/evaluations", tags=["Evaluations"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get(
    "",
    response_model=PaginatedResponse[EvaluationSummary],
    summary="List evaluations",
)
def list_evaluations(
    session: SessionDependency,
    model_run_id: Optional[UUID] = None,
    evaluator_type: Optional[str] = None,
    evaluator_name: Optional[str] = None,
    passed: Optional[bool] = None,
    minimum_score: Optional[Decimal] = None,
    maximum_score: Optional[Decimal] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[EvaluationSummary]:
    repository = EvaluationRepository(session)
    filters = {
        "model_run_id": model_run_id,
        "evaluator_type": evaluator_type,
        "evaluator_name": evaluator_name,
        "passed": passed,
        "minimum_overall_score": minimum_score,
        "maximum_overall_score": maximum_score,
    }
    return PaginatedResponse(
        items=repository.list_evaluations(limit, offset, **filters),
        total=repository.count_evaluations(**filters),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{evaluation_id}",
    response_model=EvaluationDetail,
    summary="Get evaluation details",
)
def get_evaluation(
    evaluation_id: UUID, session: SessionDependency
) -> EvaluationDetail:
    evaluation = EvaluationRepository(session).get_by_id(evaluation_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return evaluation
