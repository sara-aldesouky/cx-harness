"""Read-only order-item endpoints."""

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import OrderItemRepository
from app.schemas.common import PaginatedResponse
from app.schemas.order_item import OrderItemDetail, OrderItemSummary


router = APIRouter(prefix="/order-items", tags=["Order Items"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get(
    "", response_model=PaginatedResponse[OrderItemSummary], summary="List order items"
)
def list_order_items(
    session: SessionDependency,
    order_id: Optional[UUID] = None,
    item_status: Optional[str] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[OrderItemSummary]:
    repository = OrderItemRepository(session)
    filters = {"order_id": order_id, "item_status": item_status}
    return PaginatedResponse(
        items=repository.list_items(limit, offset, **filters),
        total=repository.count_items(**filters),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{item_id}", response_model=OrderItemDetail, summary="Get order-item details"
)
def get_order_item(item_id: UUID, session: SessionDependency) -> OrderItemDetail:
    item = OrderItemRepository(session).get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Order item not found")
    return item
