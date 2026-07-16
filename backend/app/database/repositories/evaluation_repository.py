"""Read-only evaluation queries."""

from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import Evaluation
from app.database.models.evaluation import EVALUATOR_TYPES
from app.database.repositories._common import (
    DEFAULT_LIMIT,
    RepositoryValidationError,
    validate_filter,
    validate_pagination,
)


class EvaluationRepository:
    """Provide read-only access to model-run evaluation results."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_evaluations(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        *,
        model_run_id: Optional[UUID] = None,
        evaluator_type: Optional[str] = None,
        evaluator_name: Optional[str] = None,
        passed: Optional[bool] = None,
        minimum_overall_score: Optional[Decimal] = None,
        maximum_overall_score: Optional[Decimal] = None,
    ) -> list[Evaluation]:
        criteria = self._build_filter_criteria(
            model_run_id=model_run_id,
            evaluator_type=evaluator_type,
            evaluator_name=evaluator_name,
            passed=passed,
            minimum_overall_score=minimum_overall_score,
            maximum_overall_score=maximum_overall_score,
        )
        return self._list_filtered(criteria, limit, offset)

    def count_evaluations(
        self,
        *,
        model_run_id: Optional[UUID] = None,
        evaluator_type: Optional[str] = None,
        evaluator_name: Optional[str] = None,
        passed: Optional[bool] = None,
        minimum_overall_score: Optional[Decimal] = None,
        maximum_overall_score: Optional[Decimal] = None,
    ) -> int:
        criteria = self._build_filter_criteria(
            model_run_id=model_run_id,
            evaluator_type=evaluator_type,
            evaluator_name=evaluator_name,
            passed=passed,
            minimum_overall_score=minimum_overall_score,
            maximum_overall_score=maximum_overall_score,
        )
        statement = select(func.count()).select_from(Evaluation)
        if criteria:
            statement = statement.where(*criteria)
        return self._session.scalar(statement) or 0

    def _build_filter_criteria(
        self,
        *,
        model_run_id: Optional[UUID],
        evaluator_type: Optional[str],
        evaluator_name: Optional[str],
        passed: Optional[bool],
        minimum_overall_score: Optional[Decimal],
        maximum_overall_score: Optional[Decimal],
    ) -> list:
        if evaluator_type is not None:
            validate_filter(
                evaluator_type, EVALUATOR_TYPES, "evaluation evaluator type"
            )
        minimum, maximum = self._validate_score_range(
            minimum_overall_score, maximum_overall_score
        )
        criteria = []
        if model_run_id is not None:
            criteria.append(Evaluation.model_run_id == model_run_id)
        if evaluator_type is not None:
            criteria.append(Evaluation.evaluator_type == evaluator_type)
        if evaluator_name is not None:
            criteria.append(Evaluation.evaluator_name == evaluator_name)
        if passed is not None:
            criteria.append(Evaluation.passed.is_(passed))
        if minimum is not None:
            criteria.append(Evaluation.overall_score >= minimum)
        if maximum is not None:
            criteria.append(Evaluation.overall_score <= maximum)
        return criteria

    def get_by_id(self, evaluation_id: UUID) -> Optional[Evaluation]:
        return self._session.scalar(
            select(Evaluation).where(Evaluation.id == evaluation_id)
        )

    def get_with_model_run(self, evaluation_id: UUID) -> Optional[Evaluation]:
        statement = (
            select(Evaluation)
            .where(Evaluation.id == evaluation_id)
            .options(joinedload(Evaluation.model_run))
        )
        return self._session.scalar(statement)

    def list_by_model_run(
        self,
        model_run_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Evaluation]:
        return self._list_filtered(
            [Evaluation.model_run_id == model_run_id], limit, offset
        )

    def list_by_evaluator_type(
        self,
        evaluator_type: str,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Evaluation]:
        validate_filter(
            evaluator_type, EVALUATOR_TYPES, "evaluation evaluator type"
        )
        return self._list_filtered(
            [Evaluation.evaluator_type == evaluator_type], limit, offset
        )

    def list_by_evaluator_name(
        self,
        evaluator_name: str,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Evaluation]:
        return self._list_filtered(
            [Evaluation.evaluator_name == evaluator_name], limit, offset
        )

    def list_passed(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Evaluation]:
        return self._list_filtered([Evaluation.passed.is_(True)], limit, offset)

    def list_failed(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Evaluation]:
        return self._list_filtered([Evaluation.passed.is_(False)], limit, offset)

    def list_by_minimum_overall_score(
        self,
        score: Decimal,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Evaluation]:
        minimum = self._validate_score(score, "minimum overall score")
        return self._list_filtered(
            [Evaluation.overall_score >= minimum], limit, offset
        )

    def list_by_score_range(
        self,
        min_score: Decimal,
        max_score: Decimal,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Evaluation]:
        minimum, maximum = self._validate_score_range(min_score, max_score)
        return self._list_filtered(
            [
                Evaluation.overall_score >= minimum,
                Evaluation.overall_score <= maximum,
            ],
            limit,
            offset,
        )

    def latest_evaluation(
        self, model_run_id: Optional[UUID] = None
    ) -> Optional[Evaluation]:
        return self._extreme_evaluation(model_run_id, descending=True)

    def earliest_evaluation(
        self, model_run_id: Optional[UUID] = None
    ) -> Optional[Evaluation]:
        return self._extreme_evaluation(model_run_id, descending=False)

    def _list_filtered(
        self, criteria: list, limit: int, offset: int
    ) -> list[Evaluation]:
        validate_pagination(limit, offset)
        statement = select(Evaluation)
        if criteria:
            statement = statement.where(*criteria)
        statement = (
            statement.order_by(
                Evaluation.evaluated_at.desc(), Evaluation.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def _extreme_evaluation(
        self, model_run_id: Optional[UUID], *, descending: bool
    ) -> Optional[Evaluation]:
        statement = select(Evaluation)
        if model_run_id is not None:
            statement = statement.where(Evaluation.model_run_id == model_run_id)
        if descending:
            statement = statement.order_by(
                Evaluation.evaluated_at.desc(), Evaluation.id.desc()
            )
        else:
            statement = statement.order_by(
                Evaluation.evaluated_at, Evaluation.id
            )
        return self._session.scalar(statement.limit(1))

    @classmethod
    def _validate_score_range(
        cls,
        min_score: Optional[Decimal],
        max_score: Optional[Decimal],
    ) -> tuple[Optional[Decimal], Optional[Decimal]]:
        minimum = (
            cls._validate_score(min_score, "minimum overall score")
            if min_score is not None
            else None
        )
        maximum = (
            cls._validate_score(max_score, "maximum overall score")
            if max_score is not None
            else None
        )
        if minimum is not None and maximum is not None and minimum > maximum:
            raise RepositoryValidationError(
                "minimum overall score must not exceed maximum overall score"
            )
        return minimum, maximum

    @staticmethod
    def _validate_score(score: Decimal, field_name: str) -> Decimal:
        if isinstance(score, bool):
            raise RepositoryValidationError(
                f"{field_name} must be a number between 0 and 5"
            )
        try:
            normalized = Decimal(str(score))
        except (InvalidOperation, TypeError, ValueError):
            raise RepositoryValidationError(
                f"{field_name} must be a number between 0 and 5"
            ) from None
        if not normalized.is_finite() or not Decimal("0") <= normalized <= Decimal("5"):
            raise RepositoryValidationError(
                f"{field_name} must be between 0 and 5"
            )
        return normalized
