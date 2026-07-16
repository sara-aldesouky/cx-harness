"""Read-only customer endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.database.repositories import CustomerRepository
from app.schemas.common import PaginatedResponse
from app.schemas.customer import CustomerDetail, CustomerSummary


router = APIRouter(prefix="/customers", tags=["Customers"])
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.get("", response_model=PaginatedResponse[CustomerSummary], summary="List customers")
def list_customers(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[CustomerSummary]:
    repository = CustomerRepository(session)
    return PaginatedResponse(
        items=repository.list_customers(limit, offset),
        total=repository.count(),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{customer_id}",
    response_model=CustomerDetail,
    summary="Get customer details",
)
def get_customer(customer_id: UUID, session: SessionDependency) -> CustomerDetail:
    customer = CustomerRepository(session).get_with_orders(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
