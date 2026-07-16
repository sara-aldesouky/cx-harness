"""Read-only conversation endpoints."""

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import ConversationRepository, MessageRepository
from app.schemas.common import PaginatedResponse
from app.schemas.conversation import ConversationDetail, ConversationSummary
from app.schemas.message import MessageSummary


router = APIRouter(prefix="/conversations", tags=["Conversations"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get(
    "",
    response_model=PaginatedResponse[ConversationSummary],
    summary="List conversations",
)
def list_conversations(
    session: SessionDependency,
    customer_id: Optional[UUID] = None,
    related_order_id: Optional[UUID] = None,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[ConversationSummary]:
    repository = ConversationRepository(session)
    filters = {
        "customer_id": customer_id,
        "related_order_id": related_order_id,
        "status": status,
        "channel": channel,
    }
    return PaginatedResponse(
        items=repository.list_conversations(limit, offset, **filters),
        total=repository.count_conversations(**filters),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=PaginatedResponse[MessageSummary],
    summary="Get ordered conversation messages",
)
def get_conversation_messages(
    conversation_id: UUID,
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[MessageSummary]:
    if ConversationRepository(session).get_by_id(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    repository = MessageRepository(session)
    return PaginatedResponse(
        items=repository.get_conversation_history(conversation_id, limit, offset),
        total=repository.count_messages(conversation_id=conversation_id),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Get conversation details",
)
def get_conversation(
    conversation_id: UUID, session: SessionDependency
) -> ConversationDetail:
    conversation = ConversationRepository(session).get_with_details(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation
