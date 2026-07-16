"""Read-only model-run queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database.models import ModelRun
from app.database.models.model_run import MODEL_RUN_PROVIDERS, MODEL_RUN_STATUSES
from app.database.repositories._common import (
    DEFAULT_LIMIT,
    validate_filter,
    validate_pagination,
)


class ModelRunRepository:
    """Provide read-only access to model execution telemetry."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_model_runs(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        *,
        conversation_id: Optional[UUID] = None,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        status: Optional[str] = None,
        success: Optional[bool] = None,
    ) -> list[ModelRun]:
        return self._list_filtered(
            self._build_filter_criteria(
                conversation_id=conversation_id,
                provider=provider,
                model_name=model_name,
                status=status,
                success=success,
            ),
            limit,
            offset,
        )

    def get_by_id(self, model_run_id: UUID) -> Optional[ModelRun]:
        return self._session.scalar(
            select(ModelRun).where(ModelRun.id == model_run_id)
        )

    def count(
        self,
        *,
        conversation_id: Optional[UUID] = None,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        status: Optional[str] = None,
        success: Optional[bool] = None,
    ) -> int:
        return self.count_model_runs(
            conversation_id=conversation_id,
            provider=provider,
            model_name=model_name,
            status=status,
            success=success,
        )

    def count_model_runs(
        self,
        *,
        conversation_id: Optional[UUID] = None,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        status: Optional[str] = None,
        success: Optional[bool] = None,
    ) -> int:
        criteria = self._build_filter_criteria(
            conversation_id=conversation_id,
            provider=provider,
            model_name=model_name,
            status=status,
            success=success,
        )
        statement = select(func.count()).select_from(ModelRun)
        if criteria:
            statement = statement.where(*criteria)
        return self._session.scalar(statement) or 0

    def list_by_conversation_id(
        self,
        conversation_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[ModelRun]:
        return self.list_model_runs(limit, offset, conversation_id=conversation_id)

    def list_by_provider(
        self, provider: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        return self.list_model_runs(limit, offset, provider=provider)

    def list_by_model(
        self, model_name: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        return self.list_model_runs(limit, offset, model_name=model_name)

    def list_by_status(
        self, status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        return self.list_model_runs(limit, offset, status=status)

    def get_latest(
        self, conversation_id: Optional[UUID] = None
    ) -> Optional[ModelRun]:
        statement = select(ModelRun)
        if conversation_id is not None:
            statement = statement.where(
                ModelRun.conversation_id == conversation_id
            )
        statement = statement.order_by(
            ModelRun.started_at.desc(), ModelRun.id.desc()
        ).limit(1)
        return self._session.scalar(statement)

    def list_successful(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        return self._list_filtered(ModelRun.success.is_(True), limit, offset)

    def list_failed(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        return self._list_filtered(ModelRun.status == "failed", limit, offset)

    def get_with_details(self, model_run_id: UUID) -> Optional[ModelRun]:
        statement = (
            select(ModelRun)
            .where(ModelRun.id == model_run_id)
            .options(
                selectinload(ModelRun.tool_calls),
                selectinload(ModelRun.evaluations),
            )
        )
        model_run = self._session.scalar(statement)
        if model_run is not None:
            model_run.tool_calls.sort(
                key=lambda tool_call: (tool_call.requested_at, tool_call.id),
                reverse=True,
            )
            model_run.evaluations.sort(
                key=lambda evaluation: (
                    evaluation.evaluated_at,
                    evaluation.id,
                ),
                reverse=True,
            )
        return model_run

    @staticmethod
    def _build_filter_criteria(
        *,
        conversation_id: Optional[UUID],
        provider: Optional[str],
        model_name: Optional[str],
        status: Optional[str],
        success: Optional[bool],
    ) -> list:
        if provider is not None:
            validate_filter(provider, MODEL_RUN_PROVIDERS, "model-run provider")
        if status is not None:
            validate_filter(status, MODEL_RUN_STATUSES, "model-run status")
        criteria = []
        if conversation_id is not None:
            criteria.append(ModelRun.conversation_id == conversation_id)
        if provider is not None:
            criteria.append(ModelRun.provider == provider)
        if model_name is not None:
            criteria.append(ModelRun.model_name == model_name)
        if status is not None:
            criteria.append(ModelRun.status == status)
        if success is not None:
            criteria.append(ModelRun.success.is_(success))
        return criteria

    def _list_filtered(
        self, criteria, limit: int, offset: int
    ) -> list[ModelRun]:
        validate_pagination(limit, offset)
        if criteria is not None and not isinstance(criteria, list):
            criteria = [criteria]
        statement = select(ModelRun)
        if criteria:
            statement = statement.where(*criteria)
        statement = (
            statement.order_by(ModelRun.started_at.desc(), ModelRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
