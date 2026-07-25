"""Write boundary dedicated to the model-pipeline invocation lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.database.models import ModelRun
from app.database.models.model_run import MODEL_RUN_PROVIDERS


class ModelRunAuditWriter(Protocol):
    """Minimal persistence contract consumed by the provider-neutral pipeline."""

    def create_running(
        self,
        *,
        conversation_id: UUID,
        provider: str,
        model_name: str,
        started_at: datetime,
    ) -> UUID: ...

    def finalize(
        self,
        model_run_id: UUID,
        *,
        status: str,
        success: bool,
        finished_at: datetime,
        latency_ms: int,
        error_message: Optional[str],
    ) -> None: ...


class ModelRunAuditRepository:
    """Create and finalize existing ModelRun rows around model invocation."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_running(
        self,
        *,
        conversation_id: UUID,
        provider: str,
        model_name: str,
        started_at: datetime,
    ) -> UUID:
        if provider not in MODEL_RUN_PROVIDERS:
            raise ValueError(f"unsupported persisted model provider: {provider}")
        model_run = ModelRun(
            conversation_id=conversation_id,
            provider=provider,
            model_name=model_name,
            status="running",
            success=False,
            started_at=started_at,
        )
        with self._session_factory.begin() as session:
            session.add(model_run)
            session.flush()
            model_run_id = model_run.id
        return model_run_id

    def finalize(
        self,
        model_run_id: UUID,
        *,
        status: str,
        success: bool,
        finished_at: datetime,
        latency_ms: int,
        error_message: Optional[str],
    ) -> None:
        with self._session_factory.begin() as session:
            model_run = session.get(ModelRun, model_run_id)
            if model_run is None:
                raise RuntimeError(
                    "ModelRun audit record disappeared during invocation"
                )
            model_run.status = status
            model_run.success = success
            model_run.finished_at = finished_at
            model_run.latency_ms = latency_ms
            model_run.error_message = error_message
