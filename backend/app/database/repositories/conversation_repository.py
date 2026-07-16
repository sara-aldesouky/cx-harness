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
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        *,
        customer_id: Optional[UUID] = None,
        related_order_id: Optional[UUID] = None,
        status: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> list[Conversation]:
        criteria = self._build_filter_criteria(
            customer_id=customer_id,
            related_order_id=related_order_id,
            status=status,
            channel=channel,
        )
        return self._list_filtered(criteria, limit, offset)

    def get_by_id(self, conversation_id: UUID) -> Optional[Conversation]:
        return self._session.scalar(
            select(Conversation).where(Conversation.id == conversation_id)
        )

    def count(
        self,
        *,
        customer_id: Optional[UUID] = None,
        related_order_id: Optional[UUID] = None,
        status: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> int:
        return self.count_conversations(
            customer_id=customer_id,
            related_order_id=related_order_id,
            status=status,
            channel=channel,
        )

    def count_conversations(
        self,
        *,
        customer_id: Optional[UUID] = None,
        related_order_id: Optional[UUID] = None,
        status: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> int:
        criteria = self._build_filter_criteria(
            customer_id=customer_id,
            related_order_id=related_order_id,
            status=status,
            channel=channel,
        )
        statement = select(func.count()).select_from(Conversation)
        if criteria:
            statement = statement.where(*criteria)
        return self._session.scalar(statement) or 0

    def list_by_customer_id(
        self,
        customer_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Conversation]:
        return self.list_conversations(limit, offset, customer_id=customer_id)

    def list_by_related_order_id(
        self,
        order_id: UUID,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Conversation]:
        return self.list_conversations(
            limit, offset, related_order_id=order_id
        )

    def list_by_status(
        self, status: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        return self.list_conversations(limit, offset, status=status)

    def list_by_channel(
        self, channel: str, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        return self.list_conversations(limit, offset, channel=channel)

    def list_active(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        return self._list_filtered(
            [Conversation.status.in_(ACTIVE_CONVERSATION_STATUSES)], limit, offset
        )

    def list_closed(
        self, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Conversation]:
        return self._list_filtered(
            [Conversation.status.in_(CLOSED_CONVERSATION_STATUSES)], limit, offset
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

    @staticmethod
    def _build_filter_criteria(
        *,
        customer_id: Optional[UUID],
        related_order_id: Optional[UUID],
        status: Optional[str],
        channel: Optional[str],
    ) -> list:
        if status is not None:
            validate_filter(status, CONVERSATION_STATUSES, "conversation status")
        if channel is not None:
            validate_filter(channel, CONVERSATION_CHANNELS, "conversation channel")
        criteria = []
        if customer_id is not None:
            criteria.append(Conversation.customer_id == customer_id)
        if related_order_id is not None:
            criteria.append(Conversation.related_order_id == related_order_id)
        if status is not None:
            criteria.append(Conversation.status == status)
        if channel is not None:
            criteria.append(Conversation.channel == channel)
        return criteria

    def _list_filtered(
        self, criteria: list, limit: int, offset: int
    ) -> list[Conversation]:
        validate_pagination(limit, offset)
        statement = select(Conversation)
        if criteria:
            statement = statement.where(*criteria)
        statement = (
            statement.order_by(
                Conversation.started_at.desc(), Conversation.id
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(statement).all())
