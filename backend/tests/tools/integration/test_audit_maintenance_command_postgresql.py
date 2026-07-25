"""PostgreSQL integration tests for the explicit maintenance command."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from io import StringIO
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import ToolCall
from app.database.repositories import ToolCallAuditRepository
from app.services import ToolCallAuditMaintenanceService
from app.services import classify_database_target
from scripts.maintain_tool_call_audits import main
from tests.repositories.conftest import table_counts
from tests.conftest import get_test_database_url


pytestmark = pytest.mark.integration


@pytest.fixture
def command_database(test_engine: Engine) -> Generator[dict[str, object], None, None]:
    with Session(test_engine) as session:
        counts_before = table_counts(session)
    factory = sessionmaker(
        bind=test_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    execution_ids: list[UUID] = []
    yield {"factory": factory, "execution_ids": execution_ids}
    with factory.begin() as session:
        if execution_ids:
            session.execute(
                delete(ToolCall).where(ToolCall.execution_id.in_(execution_ids))
            )
    with Session(test_engine) as session:
        assert table_counts(session) == counts_before


def create_audit(
    command_database,
    *,
    status: str,
    started_at: datetime,
    created_at: datetime,
) -> UUID:
    record = ToolCall(
        execution_id=uuid4(),
        model_run_id=None,
        tool_name="maintenance_command_test",
        tool_version="1.0.0",
        status=status,
        input_json={},
        success=status == "completed",
        requested_at=started_at,
        started_at=started_at,
        finished_at=started_at if status != "running" else None,
        created_at=created_at,
    )
    with command_database["factory"].begin() as session:
        session.add(record)
    command_database["execution_ids"].append(record.execution_id)
    return record.execution_id


def service(command_database) -> ToolCallAuditMaintenanceService:
    return ToolCallAuditMaintenanceService(
        ToolCallAuditRepository(command_database["factory"]),
        retention_days=90,
        stale_after_seconds=300,
    )


def run_command(arguments, maintenance):
    output = StringIO()
    errors = StringIO()
    code = main(
        arguments,
        service=maintenance,
        target=classify_database_target(get_test_database_url(), "test"),
        input_fn=lambda prompt: "cx_harness_test",
        stdout=output,
        stderr=errors,
    )
    assert errors.getvalue() == ""
    return code, output.getvalue()


def load(command_database, execution_id: UUID):
    with command_database["factory"]() as session:
        return session.scalar(
            select(ToolCall).where(ToolCall.execution_id == execution_id)
        )


def test_dry_run_reports_candidates_without_writes(command_database) -> None:
    now = datetime.now(timezone.utc)
    stale_id = create_audit(
        command_database,
        status="running",
        started_at=now - timedelta(hours=1),
        created_at=now - timedelta(hours=1),
    )
    expired_id = create_audit(
        command_database,
        status="completed",
        started_at=now - timedelta(days=100),
        created_at=now - timedelta(days=100),
    )

    code, output = run_command(["dry-run"], service(command_database))

    assert code == 0
    assert "would be recovered: 1" in output
    assert "would be deleted: 1" in output
    assert load(command_database, stale_id).status == "running"
    assert load(command_database, expired_id) is not None


def test_recover_mode_updates_only_stale_running_rows(command_database) -> None:
    now = datetime.now(timezone.utc)
    stale_id = create_audit(
        command_database,
        status="running",
        started_at=now - timedelta(hours=1),
        created_at=now,
    )
    recent_id = create_audit(
        command_database,
        status="running",
        started_at=now - timedelta(seconds=30),
        created_at=now,
    )

    code, output = run_command(["recover"], service(command_database))

    assert code == 0
    assert "Recovered stale executions: 1" in output
    assert load(command_database, stale_id).status == "error"
    assert load(command_database, recent_id).status == "running"


def test_cleanup_force_removes_only_expired_rows(command_database) -> None:
    now = datetime.now(timezone.utc)
    expired_id = create_audit(
        command_database,
        status="completed",
        started_at=now - timedelta(days=100),
        created_at=now - timedelta(days=100),
    )
    recent_id = create_audit(
        command_database,
        status="completed",
        started_at=now - timedelta(days=1),
        created_at=now - timedelta(days=1),
    )

    code, output = run_command(["cleanup", "--force"], service(command_database))

    assert code == 0
    assert "Deleted expired audit records: 1" in output
    assert load(command_database, expired_id) is None
    assert load(command_database, recent_id) is not None


def test_combined_recovers_then_cleans_up_atomically(command_database) -> None:
    now = datetime.now(timezone.utc)
    stale_id = create_audit(
        command_database,
        status="running",
        started_at=now - timedelta(hours=1),
        created_at=now,
    )
    expired_id = create_audit(
        command_database,
        status="completed",
        started_at=now - timedelta(days=100),
        created_at=now - timedelta(days=100),
    )

    code, output = run_command(["combined", "--force"], service(command_database))

    assert code == 0
    assert "Recovered stale executions: 1" in output
    assert "Deleted expired audit records: 1" in output
    assert load(command_database, stale_id).status == "error"
    assert load(command_database, expired_id) is None

    with command_database["factory"]() as session:
        remaining = session.scalar(
            select(func.count())
            .select_from(ToolCall)
            .where(ToolCall.execution_id.in_([stale_id, expired_id]))
        )
    assert remaining == 1
