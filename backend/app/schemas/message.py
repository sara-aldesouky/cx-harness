"""Message response schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from app.schemas.common import ORMResponse


class MessageSummary(ORMResponse):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    language: Optional[str]
    sequence_number: int
    created_at: datetime
