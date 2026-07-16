"""Read-only order endpoints."""

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import OrderRepository
from app.schemas.common import PaginatedResponse
from app.schemas.order import OrderDetail, OrderSummary


router = APIRouter(prefix="/orders", tags=["Orders"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get("", response_model=PaginatedResponse[OrderSummary], summary="List orders")
def list_orders(
    session: SessionDependency,
    customer_id: Optional[UUID] = None,
    status: Optional[str] = None,
    payment_status: Optional[str] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[OrderSummary]:
    repository = OrderRepository(session)
    filters = {
        "customer_id": customer_id,
        "status": status,
        "payment_status": payment_status,
    }
    return PaginatedResponse(
        items=repository.list_orders(limit, offset, **filters),
        total=repository.count_orders(**filters),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/by-number/{order_number}",
    response_model=OrderDetail,
    summary="Get order by order number",
)
def get_order_by_number(order_number: str, session: SessionDependency) -> OrderDetail:
    repository = OrderRepository(session)
    order = repository.get_by_order_number(order_number)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return repository.get_with_customer_and_items(order.id)


@router.get("/{order_id}", response_model=OrderDetail, summary="Get order details")
def get_order(order_id: UUID, session: SessionDependency) -> OrderDetail:
    order = OrderRepository(session).get_with_customer_and_items(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
