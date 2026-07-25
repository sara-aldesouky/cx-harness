"""Real PostgreSQL integration tests for ``get_order_status``."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app.database.models import Customer, Order, ToolCall
from app.database.repositories import ToolCallRepository
from app.tools import (
    BaseTool,
    ExecutionContext,
    GetOrderStatusInput,
    GetOrderStatusTool,
    ToolExecutor,
    ToolCategory,
    ToolMetadata,
    ToolRegistry,
    ToolStatus,
)
from tests.models.factories import create_customer, create_order
from tests.repositories.conftest import table_counts


pytestmark = pytest.mark.integration


class ExplodingInput(BaseModel):
    value: str


class ExplodingOutput(BaseModel):
    value: str


class ExplodingAuditTool(BaseTool[ExplodingInput, ExplodingOutput]):
    """Test-only tool used to prove persistent exception auditing."""

    metadata = ToolMetadata(
        name="integration_audit_error",
        version="1.0.0",
        description="Raise a test-only unexpected exception.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("audit_integration_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
    )
    input_schema = ExplodingInput
    output_schema = ExplodingOutput

    def execute(self, context, input_model):
        raise RuntimeError("integration audit failure")


@pytest.fixture(scope="module")
def commerce_records(test_engine: Engine) -> Generator[dict[str, object], None, None]:
    """Commit a minimal owned/unowned graph and remove exactly those rows."""

    with Session(test_engine) as verification_session:
        counts_before = table_counts(verification_session)

    suffix = uuid4().hex[:12]
    with Session(test_engine) as session:
        customer = create_customer(
            session,
            email=f"tool-owner-{suffix}@example.test",
            phone=f"+209{suffix[:10]}",
        )
        other_customer = create_customer(
            session,
            email=f"tool-other-{suffix}@example.test",
            phone=f"+208{suffix[:10]}",
        )
        owned_order = create_order(
            session,
            customer,
            order_number=f"TOOL-OWNED-{suffix}",
            status="dispatched",
            payment_status="paid",
            estimated_delivery_time=datetime(
                2026, 7, 30, 12, 0, tzinfo=timezone.utc
            ),
        )
        other_order = create_order(
            session,
            other_customer,
            order_number=f"TOOL-OTHER-{suffix}",
            status="preparing",
            payment_status="paid",
        )
        records = {
            "customer_id": customer.id,
            "other_customer_id": other_customer.id,
            "owned_order_id": owned_order.id,
            "other_order_id": other_order.id,
            "owned_order_number": owned_order.order_number,
            "other_order_number": other_order.order_number,
            "owned_status": owned_order.status,
            "owned_payment_status": owned_order.payment_status,
            "owned_estimated_delivery": owned_order.estimated_delivery_time,
            "owned_created_at": owned_order.created_at,
        }
        session.commit()

    try:
        yield records
    finally:
        with Session(test_engine) as cleanup_session:
            cleanup_session.execute(
                delete(ToolCall).where(
                    ToolCall.customer_id.in_(
                        [records["customer_id"], records["other_customer_id"]]
                    )
                )
            )
            cleanup_session.execute(
                delete(Order).where(
                    Order.id.in_(
                        [records["owned_order_id"], records["other_order_id"]]
                    )
                )
            )
            cleanup_session.execute(
                delete(Customer).where(
                    Customer.id.in_(
                        [records["customer_id"], records["other_customer_id"]]
                    )
                )
            )
            cleanup_session.commit()

        with Session(test_engine) as verification_session:
            assert table_counts(verification_session) == counts_before


def context(customer_id: UUID) -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(),
        execution_id=uuid4(),
        customer_id=customer_id,
    )


def execute(customer_id: UUID, order_id: UUID):
    registry = ToolRegistry()
    registry.register(GetOrderStatusTool)
    execution_context = context(customer_id)
    result = ToolExecutor(registry).execute(
        "get_order_status",
        "1.0.0",
        execution_context,
        GetOrderStatusInput(order_id=order_id),
    )
    return execution_context, result


def audit_record(test_engine: Engine, execution_id: UUID) -> ToolCall:
    with Session(test_engine) as session:
        record = ToolCallRepository(session).get_by_execution_id(execution_id)
        assert record is not None
        session.expunge(record)
        return record


def test_owned_order_lookup_uses_real_postgresql(
    test_engine, commerce_records
) -> None:
    execution_context, result = execute(
        commerce_records["customer_id"], commerce_records["owned_order_id"]
    )

    assert result.status is ToolStatus.SUCCESS
    assert result.error is None
    assert result.data is not None
    assert result.data.order_number == commerce_records["owned_order_number"]
    assert result.data.status == commerce_records["owned_status"]
    assert result.data.payment_status == commerce_records["owned_payment_status"]
    assert result.data.estimated_delivery == commerce_records[
        "owned_estimated_delivery"
    ]
    assert result.data.created_at == commerce_records["owned_created_at"]
    audit = audit_record(test_engine, execution_context.execution_id)
    assert audit.status == "completed"
    assert audit.success is True
    assert audit.tool_name == "get_order_status"
    assert audit.tool_version == "1.0.0"
    assert audit.customer_id == commerce_records["customer_id"]
    assert audit.started_at is not None
    assert audit.finished_at is not None
    assert audit.latency_ms is not None and audit.latency_ms >= 0


def test_missing_order_returns_safe_business_failure(
    test_engine, commerce_records
) -> None:
    execution_context, result = execute(commerce_records["customer_id"], uuid4())

    assert result.status is ToolStatus.FAILURE
    assert result.data is None
    assert result.error is not None
    assert result.error.error_code == "order_not_found"
    audit = audit_record(test_engine, execution_context.execution_id)
    assert audit.status == "failed"
    assert audit.success is False
    assert audit.error_code == "order_not_found"
    assert audit.exception_type is None


def test_ownership_protection_exposes_no_order_details(
    test_engine, commerce_records
) -> None:
    execution_context, result = execute(
        commerce_records["customer_id"], commerce_records["other_order_id"]
    )

    assert result.status is ToolStatus.FAILURE
    assert result.data is None
    assert result.error is not None
    assert result.error.error_code == "order_access_denied"
    serialized = result.model_dump(mode="json")
    assert commerce_records["other_order_number"] not in str(serialized)
    audit = audit_record(test_engine, execution_context.execution_id)
    assert audit.status == "failed"
    assert audit.error_code == "order_access_denied"
    assert audit.output_json is not None
    assert commerce_records["other_order_number"] not in str(audit.output_json)


def test_unexpected_exception_is_persisted_and_propagated(
    test_engine, commerce_records
) -> None:
    registry = ToolRegistry()
    registry.register(ExplodingAuditTool)
    execution_context = context(commerce_records["customer_id"])

    with pytest.raises(RuntimeError, match="integration audit failure"):
        ToolExecutor(registry).execute(
            "integration_audit_error",
            "1.0.0",
            execution_context,
            ExplodingInput(value="explode"),
        )

    audit = audit_record(test_engine, execution_context.execution_id)
    assert audit.status == "error"
    assert audit.success is False
    assert audit.exception_type == "RuntimeError"
    assert audit.error_code is None
    assert audit.finished_at is not None
    assert audit.latency_ms is not None and audit.latency_ms >= 0
