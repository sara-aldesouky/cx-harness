"""PostgreSQL integration tests for audit safety and maintenance."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import ToolCall
from app.database.repositories import (
    ToolCallAuditRepository,
    ToolCallRepository,
)
from app.services import ToolCallAuditMaintenanceService
from app.tools import (
    BaseTool,
    ExecutionContext,
    ToolCategory,
    ToolExecutor,
    ToolMetadata,
    ToolRegistry,
    ToolResult,
    ToolStatus,
)
from app.tools.audit_payload import REDACTED_MARKER
from tests.repositories.conftest import table_counts


pytestmark = pytest.mark.integration


class SafetyInput(BaseModel):
    order_id: str
    password: str
    nested: dict[str, object]
    content: str = ""


class SafetyOutput(BaseModel):
    status: str
    access_token: str
    content: str = ""


class AuditSafetyTool(BaseTool[SafetyInput, SafetyOutput]):
    metadata = ToolMetadata(
        name="audit_safety_test",
        version="1.0.0",
        description="Test-only audit payload safety tool.",
        category=ToolCategory.SYSTEM,
        supported_use_cases=("audit_safety_test",),
        requires_customer_identity=False,
        requires_order_ownership=False,
        requires_policy_check=False,
        is_read_only=True,
    )
    input_schema = SafetyInput
    output_schema = SafetyOutput

    def execute(self, context, input_model):
        return ToolResult[SafetyOutput](
            status=ToolStatus.SUCCESS,
            data=SafetyOutput(
                status="ok",
                access_token="output-secret-token",
                content=input_model.content,
            ),
        )


@pytest.fixture
def audit_environment(test_engine: Engine) -> Generator[dict[str, object], None, None]:
    with Session(test_engine) as session:
        counts_before = table_counts(session)

    factory = sessionmaker(
        bind=test_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    execution_ids: list[UUID] = []
    yield {
        "factory": factory,
        "execution_ids": execution_ids,
        "counts_before": counts_before,
    }

    with factory.begin() as session:
        if execution_ids:
            session.execute(
                delete(ToolCall).where(ToolCall.execution_id.in_(execution_ids))
            )
    with Session(test_engine) as session:
        assert table_counts(session) == counts_before


def execution_context(audit_environment) -> ExecutionContext:
    context = ExecutionContext(trace_id=uuid4(), execution_id=uuid4())
    audit_environment["execution_ids"].append(context.execution_id)
    return context


def execute_safety_tool(audit_environment, input_model, max_bytes):
    registry = ToolRegistry()
    registry.register(AuditSafetyTool)
    context = execution_context(audit_environment)
    repository = ToolCallAuditRepository(audit_environment["factory"])
    result = ToolExecutor(
        registry,
        repository,
        audit_payload_max_bytes=max_bytes,
    ).execute("audit_safety_test", "1.0.0", context, input_model)
    return context, result


def load_audit(audit_environment, execution_id: UUID) -> ToolCall:
    with audit_environment["factory"]() as session:
        record = ToolCallRepository(session).get_by_execution_id(execution_id)
        assert record is not None
        session.expunge(record)
        return record


def test_persisted_payloads_are_recursively_redacted(audit_environment) -> None:
    context, _ = execute_safety_tool(
        audit_environment,
        SafetyInput(
            order_id="safe-order-id",
            password="input-secret",
            nested={"Email": "person@example.test", "customer_id": "safe-id"},
        ),
        10_000,
    )

    audit = load_audit(audit_environment, context.execution_id)
    assert audit.input_json["password"] == REDACTED_MARKER
    assert audit.input_json["nested"]["Email"] == REDACTED_MARKER
    assert audit.input_json["nested"]["customer_id"] == REDACTED_MARKER
    assert audit.input_json["order_id"] == REDACTED_MARKER
    assert audit.output_json["data"]["access_token"] == REDACTED_MARKER
    assert audit.input_truncated is False
    assert audit.output_truncated is False


def test_oversized_payloads_persist_only_truncation_metadata(
    audit_environment,
) -> None:
    oversized = "do-not-store-" * 200
    context, _ = execute_safety_tool(
        audit_environment,
        SafetyInput(
            order_id="safe-order-id",
            password="secret",
            nested={},
            content=oversized,
        ),
        100,
    )

    audit = load_audit(audit_environment, context.execution_id)
    assert audit.input_truncated is True
    assert audit.output_truncated is True
    assert audit.input_json["_truncated"] is True
    assert audit.output_json["_truncated"] is True
    assert oversized not in str(audit.input_json)
    assert oversized not in str(audit.output_json)


def make_tool_call(
    *,
    status: str,
    started_at: datetime,
    created_at: datetime,
    finished_at: datetime = None,
) -> ToolCall:
    return ToolCall(
        execution_id=uuid4(),
        model_run_id=None,
        tool_name="maintenance_test",
        tool_version="1.0.0",
        status=status,
        input_json={},
        success=status == "completed",
        requested_at=started_at,
        started_at=started_at,
        finished_at=finished_at,
        created_at=created_at,
    )


def test_stale_recovery_is_selective_idempotent_and_persistent(
    audit_environment,
) -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    stale = make_tool_call(
        status="running",
        started_at=now - timedelta(minutes=10),
        created_at=now - timedelta(minutes=10),
    )
    recent = make_tool_call(
        status="running",
        started_at=now - timedelta(seconds=30),
        created_at=now - timedelta(seconds=30),
    )
    completed = make_tool_call(
        status="completed",
        started_at=now - timedelta(minutes=20),
        finished_at=now - timedelta(minutes=19),
        created_at=now - timedelta(minutes=20),
    )
    failed = make_tool_call(
        status="failed",
        started_at=now - timedelta(minutes=20),
        finished_at=now - timedelta(minutes=19),
        created_at=now - timedelta(minutes=20),
    )
    error = make_tool_call(
        status="error",
        started_at=now - timedelta(minutes=20),
        finished_at=now - timedelta(minutes=19),
        created_at=now - timedelta(minutes=20),
    )
    with audit_environment["factory"].begin() as session:
        session.add_all([stale, recent, completed, failed, error])
    audit_environment["execution_ids"].extend(
        [
            stale.execution_id,
            recent.execution_id,
            completed.execution_id,
            failed.execution_id,
            error.execution_id,
        ]
    )

    service = ToolCallAuditMaintenanceService(
        ToolCallAuditRepository(audit_environment["factory"]),
        retention_days=90,
        stale_after_seconds=120,
    )
    assert service.recover_stale(now) == 1
    assert service.recover_stale(now) == 0

    with audit_environment["factory"]() as session:
        recovered = session.scalar(
            select(ToolCall).where(ToolCall.execution_id == stale.execution_id)
        )
        unchanged_recent = session.scalar(
            select(ToolCall).where(ToolCall.execution_id == recent.execution_id)
        )
        unchanged_completed = session.scalar(
            select(ToolCall).where(ToolCall.execution_id == completed.execution_id)
        )
        unchanged_failed = session.scalar(
            select(ToolCall).where(ToolCall.execution_id == failed.execution_id)
        )
        unchanged_error = session.scalar(
            select(ToolCall).where(ToolCall.execution_id == error.execution_id)
        )
        assert recovered.status == "error"
        assert recovered.exception_type == "InterruptedExecution"
        assert recovered.error_code == "stale_execution_recovered"
        assert recovered.finished_at == now
        assert recovered.latency_ms == 600_000
        assert unchanged_recent.status == "running"
        assert unchanged_completed.status == "completed"
        assert unchanged_failed.status == "failed"
        assert unchanged_error.status == "error"


def test_retention_deletes_only_expired_tool_calls(audit_environment) -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    expired = make_tool_call(
        status="completed",
        started_at=now - timedelta(days=100),
        finished_at=now - timedelta(days=100) + timedelta(seconds=1),
        created_at=now - timedelta(days=100),
    )
    recent = make_tool_call(
        status="completed",
        started_at=now - timedelta(days=1),
        finished_at=now - timedelta(days=1) + timedelta(seconds=1),
        created_at=now - timedelta(days=1),
    )
    with audit_environment["factory"].begin() as session:
        session.add_all([expired, recent])
    audit_environment["execution_ids"].extend(
        [expired.execution_id, recent.execution_id]
    )

    service = ToolCallAuditMaintenanceService(
        ToolCallAuditRepository(audit_environment["factory"]),
        retention_days=90,
        stale_after_seconds=120,
    )
    assert service.delete_expired(now) == 1

    with audit_environment["factory"]() as session:
        assert session.scalar(
            select(ToolCall).where(ToolCall.execution_id == expired.execution_id)
        ) is None
        assert session.scalar(
            select(ToolCall).where(ToolCall.execution_id == recent.execution_id)
        ) is not None
