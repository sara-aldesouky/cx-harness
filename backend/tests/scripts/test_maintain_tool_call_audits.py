"""Unit tests for the audit maintenance command coordinator."""

from datetime import datetime, timezone
from io import StringIO

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.services import (
    AuditMaintenancePreview,
    DatabaseTarget,
    DatabaseTargetClassification,
)
from scripts.maintain_tool_call_audits import main


NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)
LOCAL_TARGET = DatabaseTarget(
    host="127.0.0.1",
    database="cx_harness_test",
    environment="test",
    classification=DatabaseTargetClassification.LOCAL_TEST,
)
PRODUCTION_TARGET = DatabaseTarget(
    host="database.render.com",
    database="cx_harness_production",
    environment="production",
    classification=DatabaseTargetClassification.PRODUCTION,
)
UNKNOWN_TARGET = DatabaseTarget(
    host="custom.remote.internal",
    database="cx_harness_unknown",
    environment="development",
    classification=DatabaseTargetClassification.UNKNOWN,
)


class FakeMaintenanceService:
    def __init__(self, *, stale=2, expired=3) -> None:
        self.stale = stale
        self.expired = expired
        self.calls = []

    def preview(self):
        self.calls.append("preview")
        return AuditMaintenancePreview(
            stale_count=self.stale,
            expired_count=self.expired,
            stale_cutoff=NOW,
            retention_cutoff=NOW,
        )

    def recover_stale(self):
        self.calls.append("recover")
        recovered = self.stale
        self.stale = 0
        return recovered

    def delete_expired(self):
        self.calls.append("cleanup")
        deleted = self.expired
        self.expired = 0
        return deleted

    def run_combined(self):
        self.calls.append("combined")
        recovered, deleted = self.stale, self.expired
        self.stale = self.expired = 0
        return recovered, deleted


def run(arguments, service, answers=None, target=LOCAL_TARGET):
    output = StringIO()
    errors = StringIO()
    responses = iter(answers or [target.database, "yes"])
    code = main(
        arguments,
        service=service,
        target=target,
        input_fn=lambda prompt: next(responses),
        stdout=output,
        stderr=errors,
    )
    return code, output.getvalue(), errors.getvalue()


def test_dry_run_reports_counts_and_performs_no_writes() -> None:
    service = FakeMaintenanceService(stale=4, expired=8)

    code, output, errors = run(["dry-run"], service)

    assert code == 0 and errors == ""
    assert "would be recovered: 4" in output
    assert "would be deleted: 8" in output
    assert "no database records were changed" in output
    assert service.calls == ["preview"]


def test_dry_run_clearly_reports_when_no_maintenance_is_required() -> None:
    code, output, _ = run(
        ["dry-run"], FakeMaintenanceService(stale=0, expired=0)
    )

    assert code == 0
    assert "No audit maintenance is required" in output


def test_recover_invokes_service_and_reports_count() -> None:
    service = FakeMaintenanceService(stale=4, expired=0)

    code, output, _ = run(["recover"], service)

    assert code == 0
    assert "Recovered stale executions: 4" in output
    assert "Remaining stale executions: 0" in output
    assert service.calls == ["preview", "recover", "preview"]


def test_cleanup_requires_confirmation_and_reports_deletion() -> None:
    service = FakeMaintenanceService(stale=0, expired=5)

    declined, output, _ = run(
        ["cleanup"], service, answers=[LOCAL_TARGET.database, "no"]
    )

    assert declined == 2
    assert "cancelled" in output
    assert service.calls == ["preview"]

    service = FakeMaintenanceService(stale=0, expired=5)
    accepted, output, _ = run(
        ["cleanup"], service, answers=[LOCAL_TARGET.database, "yes"]
    )
    assert accepted == 0
    assert "Deleted expired audit records: 5" in output
    assert service.calls == ["preview", "cleanup", "preview"]


def test_force_bypasses_cleanup_confirmation() -> None:
    service = FakeMaintenanceService(stale=0, expired=2)

    code = main(
        ["cleanup", "--force"],
        service=service,
        target=LOCAL_TARGET,
        input_fn=lambda prompt: LOCAL_TARGET.database,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert code == 0
    assert "cleanup" in service.calls


def test_combined_uses_atomic_service_operation_and_reports_both_counts() -> None:
    service = FakeMaintenanceService(stale=3, expired=7)

    code, output, _ = run(["combined", "--force"], service)

    assert code == 0
    assert "Recovered stale executions: 3" in output
    assert "Deleted expired audit records: 7" in output
    assert service.calls == ["preview", "combined", "preview"]


def test_production_write_requires_override_and_database_acknowledgement() -> None:
    blocked_service = FakeMaintenanceService(stale=1, expired=0)
    code, _, errors = run(
        ["recover"], blocked_service, target=PRODUCTION_TARGET
    )
    assert code == 2
    assert "Production write blocked" in errors
    assert blocked_service.calls == []

    allowed_service = FakeMaintenanceService(stale=1, expired=0)
    code, output, errors = run(
        ["recover", "--allow-production"],
        allowed_service,
        answers=[PRODUCTION_TARGET.database],
        target=PRODUCTION_TARGET,
    )
    assert code == 0 and errors == ""
    assert "Recovered stale executions: 1" in output


def test_unknown_write_requires_override() -> None:
    blocked = FakeMaintenanceService(stale=1, expired=0)
    code, _, errors = run(["recover"], blocked, target=UNKNOWN_TARGET)
    assert code == 2
    assert "Unknown-target write blocked" in errors
    assert blocked.calls == []

    allowed = FakeMaintenanceService(stale=1, expired=0)
    code, _, _ = run(
        ["recover", "--allow-unknown-target"],
        allowed,
        answers=[UNKNOWN_TARGET.database],
        target=UNKNOWN_TARGET,
    )
    assert code == 0
    assert "recover" in allowed.calls


def test_incorrect_database_acknowledgement_cancels_every_write_mode() -> None:
    for operation in ("recover", "cleanup", "combined"):
        service = FakeMaintenanceService(stale=1, expired=1)
        arguments = [operation, "--force"] if operation != "recover" else [operation]
        code, output, _ = run(
            arguments,
            service,
            answers=["wrong_database"],
        )
        assert code == 2
        assert "acknowledgement failed" in output
        assert service.calls == []


def test_force_does_not_bypass_production_target_protection() -> None:
    service = FakeMaintenanceService(stale=0, expired=1)

    code, _, errors = run(
        ["cleanup", "--force"], service, target=PRODUCTION_TARGET
    )

    assert code == 2
    assert "Production write blocked" in errors
    assert service.calls == []


@pytest.mark.parametrize(
    "error,expected_code,expected_text",
    [
        (ValueError("bad setting"), 2, "Invalid audit maintenance configuration"),
        (SQLAlchemyError("database offline"), 1, "database failure"),
        (RuntimeError("unexpected"), 1, "RuntimeError: unexpected"),
    ],
)
def test_errors_return_nonzero_exit_codes(error, expected_code, expected_text) -> None:
    class BrokenService:
        def preview(self):
            raise error

    code, _, errors = run(["dry-run"], BrokenService())

    assert code == expected_code
    assert expected_text in errors
