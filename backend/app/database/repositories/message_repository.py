"""Read-only conversation-message queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Message
from app.database.models.message import MESSAGE_LANGUAGES, MESSAGE_ROLES
from app.database.repositories._common import (
    DEFAULT_LIMIT,
    validate_filter,
    validate_pagination,
)


class MessageRepository:
    """Provide read-only access to conversation messages."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_messages(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        *,
        conversation_id: Optional[UUID] = None,
        role: Optional[str] = None,
        language: Optional[str] = None,
    ) -> list[Message]:
        criteria = self._build_filter_criteria(
            conversation_id=conversation_id, role=role, language=language
        )
        return self._list_filtered(criteria, limit, offset)

    def get_by_id(self, message_id: UUID) -> Optional[Message]:
        return self._session.scalar(select(Message).where(Message.id == message_id))

    def count(
        self,
        *,
        conversation_id: Optional[UUID] = None,
        role: Optional[str] = None,
        language: Optional[str] = None,
    ) -> int:
        return self.count_messages(
            conversation_id=conversation_id, role=role, language=language
        )

    def count_messages(
        self,
        *,
        conversation_id: Optional[UUID] = None,
        role: Optional[str] = None,
        language: Optional[str] = None,
    ) -> int:
        criteria = self._build_filter_criteria(
            conversation_id=conversation_id, role=role, language=language
        )
        statement = select(func.count()).select_from(Message)
        if criteria:
            statement = statement.where(*criteria)
        return self._session.scalar(statement) or 0

    def list_by_conversation_id(
        self,
        conversation_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Message]:
        validate_pagination(limit, offset)
        statement = select(Message).where(
            Message.conversation_id == conversation_id
        )
        statement = statement.order_by(
            Message.sequence_number, Message.id
        ).offset(offset).limit(limit)
        return list(self._session.scalars(statement).all())

    def list_by_role(
        self, role: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Message]:
        return self.list_messages(limit, offset, role=role)

    def list_by_language(
        self, language: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Message]:
        return self.list_messages(limit, offset, language=language)

    def get_latest_in_conversation(
        self, conversation_id: UUID
    ) -> Optional[Message]:
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence_number.desc(), Message.id.desc())
            .limit(1)
        )
        return self._session.scalar(statement)

    def get_earliest_in_conversation(
        self, conversation_id: UUID
    ) -> Optional[Message]:
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence_number, Message.id)
            .limit(1)
        )
        return self._session.scalar(statement)

    def get_conversation_history(
        self,
        conversation_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Message]:
        return self.list_by_conversation_id(conversation_id, limit, offset)

    @staticmethod
    def _build_filter_criteria(
        *,
        conversation_id: Optional[UUID],
        role: Optional[str],
        language: Optional[str],
    ) -> list:
        if role is not None:
            validate_filter(role, MESSAGE_ROLES, "message role")
        if language is not None:
            validate_filter(language, MESSAGE_LANGUAGES, "message language")
        criteria = []
        if conversation_id is not None:
            criteria.append(Message.conversation_id == conversation_id)
        if role is not None:
            criteria.append(Message.role == role)
        if language is not None:
            criteria.append(Message.language == language)
        return criteria

    def _list_filtered(self, criteria: list, limit: int, offset: int) -> list[Message]:
        validate_pagination(limit, offset)
        statement = select(Message)
        if criteria:
            statement = statement.where(*criteria)
        statement = (
            statement.order_by(Message.created_at, Message.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
