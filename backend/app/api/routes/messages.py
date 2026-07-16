"""Read-only message endpoints."""

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import MessageRepository
from app.schemas.common import PaginatedResponse
from app.schemas.message import MessageSummary


router = APIRouter(prefix="/messages", tags=["Messages"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get(
    "", response_model=PaginatedResponse[MessageSummary], summary="List messages"
)
def list_messages(
    session: SessionDependency,
    conversation_id: Optional[UUID] = None,
    role: Optional[str] = None,
    language: Optional[str] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[MessageSummary]:
    repository = MessageRepository(session)
    filters = {
        "conversation_id": conversation_id,
        "role": role,
        "language": language,
    }
    return PaginatedResponse(
        items=repository.list_messages(limit, offset, **filters),
        total=repository.count_messages(**filters),
        limit=limit,
        offset=offset,
    )


@router.get("/{message_id}", response_model=MessageSummary, summary="Get a message")
def get_message(message_id: UUID, session: SessionDependency) -> MessageSummary:
    message = MessageRepository(session).get_by_id(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return message
