"""Shared response-schema building blocks."""

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORMResponse(BaseModel):
    """Base for response schemas populated from ORM attributes."""

    model_config = ConfigDict(from_attributes=True)


class CustomerReference(ORMResponse):
    id: UUID
    first_name: str
    last_name: str
    email: str


class OrderReference(ORMResponse):
    id: UUID
    order_number: str
    status: str


class ConversationReference(ORMResponse):
    id: UUID
    status: str
    channel: str
    started_at: datetime


ItemT = TypeVar("ItemT")


class PaginatedResponse(BaseModel, Generic[ItemT]):
    """Typed page returned by future list endpoints."""

    items: list[ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class CountResponse(BaseModel):
    count: int = Field(ge=0)
