"""Read-only conversation queries."""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database.models import Conversation
from app.database.models.conversation import (
    CONVERSATION_CHANNELS,
    CONVERSATION_STATUSES,
)
from app.database.repositories._common import (
    DEFAULT_LIMIT,
    validate_filter,
    validate_pagination,
)


ACTIVE_CONVERSATION_STATUSES = (
    "open",
    "waiting_for_customer",
    "waiting_for_agent",
    "escalated",
)
CLOSED_CONVERSATION_STATUSES = ("resolved", "closed")


class ConversationRepository:
    """Provide read-only access to conversations and related records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_conversations(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        return self._list_filtered(None, limit, offset)

    def get_by_id(self, conversation_id: UUID) -> Optional[Conversation]:
        return self._session.scalar(
            select(Conversation).where(Conversation.id == conversation_id)
        )

    def count(self) -> int:
        return (
            self._session.scalar(select(func.count()).select_from(Conversation)) or 0
        )

    def list_by_customer_id(
        self,
        customer_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Conversation]:
        return self._list_filtered(
            Conversation.customer_id == customer_id, limit, offset
        )

    def list_by_related_order_id(
        self,
        order_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Conversation]:
        return self._list_filtered(
            Conversation.related_order_id == order_id, limit, offset
        )

    def list_by_status(
        self, status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        validate_filter(status, CONVERSATION_STATUSES, "conversation status")
        return self._list_filtered(Conversation.status == status, limit, offset)

    def list_by_channel(
        self, channel: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        validate_filter(channel, CONVERSATION_CHANNELS, "conversation channel")
        return self._list_filtered(Conversation.channel == channel, limit, offset)

    def list_active(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        return self._list_filtered(
            Conversation.status.in_(ACTIVE_CONVERSATION_STATUSES), limit, offset
        )

    def list_closed(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        return self._list_filtered(
            Conversation.status.in_(CLOSED_CONVERSATION_STATUSES), limit, offset
        )

    def get_with_details(
        self, conversation_id: UUID
    ) -> Optional[Conversation]:
        statement = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(
                joinedload(Conversation.customer),
                joinedload(Conversation.related_order),
                selectinload(Conversation.messages),
                selectinload(Conversation.model_runs),
            )
        )
        conversation = self._session.scalar(statement)
        if conversation is not None:
            conversation.messages.sort(
                key=lambda message: (message.sequence_number, message.id)
            )
            conversation.model_runs.sort(
                key=lambda run: (run.started_at, run.id), reverse=True
            )
        return conversation

    def _list_filtered(
        self, criterion, limit: int, offset: int
    ) -> list[Conversation]:
        validate_pagination(limit, offset)
        statement = select(Conversation)
        if criterion is not None:
            statement = statement.where(criterion)
        statement = (
            statement.order_by(
                Conversation.started_at.desc(), Conversation.id
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
