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
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Message]:
        validate_pagination(limit, offset)
        statement = (
            select(Message)
            .order_by(Message.created_at, Message.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def get_by_id(self, message_id: UUID) -> Optional[Message]:
        return self._session.scalar(select(Message).where(Message.id == message_id))

    def count(self) -> int:
        return self._session.scalar(select(func.count()).select_from(Message)) or 0

    def list_by_conversation_id(
        self,
        conversation_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Message]:
        validate_pagination(limit, offset)
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence_number, Message.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())

    def list_by_role(
        self, role: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Message]:
        validate_filter(role, MESSAGE_ROLES, "message role")
        return self._list_filtered(Message.role == role, limit, offset)

    def list_by_language(
        self, language: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Message]:
        validate_filter(language, MESSAGE_LANGUAGES, "message language")
        return self._list_filtered(Message.language == language, limit, offset)

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

    def _list_filtered(self, criterion, limit: int, offset: int) -> list[Message]:
        validate_pagination(limit, offset)
        statement = (
            select(Message)
            .where(criterion)
            .order_by(Message.created_at, Message.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
