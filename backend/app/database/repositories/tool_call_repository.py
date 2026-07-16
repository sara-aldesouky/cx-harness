"""Read-only tool-call queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database.models import ToolCall
from app.database.models.tool_call import TOOL_CALL_STATUSES
from app.database.repositories._common import (
    DEFAULT_LIMIT,
    validate_filter,
    validate_pagination,
)


class ToolCallRepository:
    """Provide read-only access to business-tool invocation records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_tool_calls(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        *,
        model_run_id: Optional[UUID] = None,
        status: Optional[str] = None,
        tool_name: Optional[str] = None,
        success: Optional[bool] = None,
    ) -> list[ToolCall]:
        criteria = self._build_filter_criteria(
            model_run_id=model_run_id,
            status=status,
            tool_name=tool_name,
            success=success,
        )
        return self._list_filtered(criteria, limit, offset)

    def count_tool_calls(
        self,
        *,
        model_run_id: Optional[UUID] = None,
        status: Optional[str] = None,
        tool_name: Optional[str] = None,
        success: Optional[bool] = None,
    ) -> int:
        criteria = self._build_filter_criteria(
            model_run_id=model_run_id,
            status=status,
            tool_name=tool_name,
            success=success,
        )
        statement = select(func.count()).select_from(ToolCall)
        if criteria:
            statement = statement.where(*criteria)
        return self._session.scalar(statement) or 0

    @staticmethod
    def _build_filter_criteria(
        *,
        model_run_id: Optional[UUID],
        status: Optional[str],
        tool_name: Optional[str],
        success: Optional[bool],
    ) -> list:
        if status is not None:
            validate_filter(status, TOOL_CALL_STATUSES, "tool-call status")
        criteria = []
        if model_run_id is not None:
            criteria.append(ToolCall.model_run_id == model_run_id)
        if status is not None:
            criteria.append(ToolCall.status == status)
        if tool_name is not None:
            criteria.append(ToolCall.tool_name == tool_name)
        if success is not None:
            criteria.append(ToolCall.success.is_(success))
        return criteria

    def get_by_id(self, tool_call_id: UUID) -> Optional[ToolCall]:
        return self._session.scalar(
            select(ToolCall).where(ToolCall.id == tool_call_id)
        )

    def get_with_model_run(self, tool_call_id: UUID) -> Optional[ToolCall]:
        statement = (
            select(ToolCall)
            .where(ToolCall.id == tool_call_id)
            .options(joinedload(ToolCall.model_run))
        )
        return self._session.scalar(statement)

    def list_by_model_run(
        self,
        model_run_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[ToolCall]:
        return self._list_filtered(
            [ToolCall.model_run_id == model_run_id], limit, offset
        )

    def list_by_status(
        self, status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ToolCall]:
        validate_filter(status, TOOL_CALL_STATUSES, "tool-call status")
        return self._list_filtered([ToolCall.status == status], limit, offset)

    def list_by_tool_name(
        self, tool_name: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ToolCall]:
        return self._list_filtered(
            [ToolCall.tool_name == tool_name], limit, offset
        )

    def list_successful(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ToolCall]:
        return self._list_filtered([ToolCall.success.is_(True)], limit, offset)

    def list_failed(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ToolCall]:
        return self._list_filtered([ToolCall.status == "failed"], limit, offset)

    def list_completed(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ToolCall]:
        return self._list_filtered(
            [ToolCall.status == "completed"], limit, offset
        )

    def list_requested(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[ToolCall]:
        return self._list_filtered(
            [ToolCall.status == "requested"], limit, offset
        )

    def latest_tool_call(
        self, model_run_id: Optional[UUID] = None
    ) -> Optional[ToolCall]:
        return self._extreme_tool_call(model_run_id, descending=True)

    def earliest_tool_call(
        self, model_run_id: Optional[UUID] = None
    ) -> Optional[ToolCall]:
        return self._extreme_tool_call(model_run_id, descending=False)

    def _list_filtered(
        self, criteria: list, limit: int, offset: int
    ) -> list[ToolCall]:
        validate_pagination(limit, offset)
        statement = select(ToolCall)
        if criteria:
            statement = statement.where(*criteria)
        statement = (
            statement.order_by(ToolCall.requested_at.desc(), ToolCall.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def _extreme_tool_call(
        self, model_run_id: Optional[UUID], *, descending: bool
    ) -> Optional[ToolCall]:
        statement = select(ToolCall)
        if model_run_id is not None:
            statement = statement.where(ToolCall.model_run_id == model_run_id)
        if descending:
            statement = statement.order_by(
                ToolCall.requested_at.desc(), ToolCall.id.desc()
            )
        else:
            statement = statement.order_by(
                ToolCall.requested_at, ToolCall.id
            )
        return self._session.scalar(statement.limit(1))
