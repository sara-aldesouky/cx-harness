"""Read-only model-run queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        return self._list_filtered(None, limit, offset)

    def get_by_id(self, model_run_id: UUID) -> Optional[ModelRun]:
        return self._session.scalar(
            select(ModelRun).where(ModelRun.id == model_run_id)
        )

    def count(self) -> int:
        return self._session.scalar(select(func.count()).select_from(ModelRun)) or 0

    def list_by_conversation_id(
        self,
        conversation_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[ModelRun]:
        return self._list_filtered(
            ModelRun.conversation_id == conversation_id, limit, offset
        )

    def list_by_provider(
        self, provider: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        validate_filter(provider, MODEL_RUN_PROVIDERS, "model-run provider")
        return self._list_filtered(ModelRun.provider == provider, limit, offset)

    def list_by_model(
        self, model_name: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        return self._list_filtered(ModelRun.model_name == model_name, limit, offset)

    def list_by_status(
        self, status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ModelRun]:
        validate_filter(status, MODEL_RUN_STATUSES, "model-run status")
        return self._list_filtered(ModelRun.status == status, limit, offset)

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

    def _list_filtered(
        self, criterion, limit: int, offset: int
    ) -> list[ModelRun]:
        validate_pagination(limit, offset)
        statement = select(ModelRun)
        if criterion is not None:
            statement = statement.where(criterion)
        statement = (
            statement.order_by(ModelRun.started_at.desc(), ModelRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
