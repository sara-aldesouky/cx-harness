"""PostgreSQL verification of ownership authorization through repositories."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.authorization import (
    AuthorizationFailureCode,
    OwnershipAuthorizationService,
    SQLAlchemyBusinessResourceOwnershipResolver,
)
from app.tools.context import ExecutionContext
from app.tools.execution_request import ToolExecutionRequest
from app.tools.get_order_status import GetOrderStatusTool
from app.tools.refund_capabilities import GetRefundStatusTool
from tests.models.factories import create_customer, create_order


pytestmark = pytest.mark.integration


def request(tool_name, order_number, customer_id) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        call_id=f"call-{tool_name}",
        tool_name=tool_name,
        tool_version="1.0.0",
        arguments={"order_number": order_number},
        context=ExecutionContext(
            trace_id=uuid4(),
            execution_id=uuid4(),
            customer_id=customer_id,
        ),
    )


@pytest.mark.parametrize(
    "tool_class",
    [GetOrderStatusTool, GetRefundStatusTool],
)
def test_repository_backed_ownership_allows_owner_and_denies_other_customer(
    db_session,
    tool_class,
) -> None:
    owner = create_customer(db_session)
    other = create_customer(db_session)
    create_order(db_session, owner, order_number=f"AUTH-{uuid4()}")
    order = owner.orders[0]
    authorization = OwnershipAuthorizationService(
        SQLAlchemyBusinessResourceOwnershipResolver(
            sessionmaker(
                bind=db_session.connection(),
                autoflush=False,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
        )
    )

    owned = authorization.authorize(
        request(tool_class.metadata.name, order.order_number, owner.id),
        tool_class.metadata,
    )
    denied = authorization.authorize(
        request(tool_class.metadata.name, order.order_number, other.id),
        tool_class.metadata,
    )

    assert owned.allowed is True
    assert denied.allowed is False
    assert denied.failure_code is AuthorizationFailureCode.UNAUTHORIZED_RESOURCE
