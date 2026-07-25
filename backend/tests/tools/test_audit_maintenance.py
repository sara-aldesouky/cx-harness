"""Unit tests for explicit audit retention and stale recovery cutoffs."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.services import ToolCallAuditMaintenanceService


class RecordingMaintenanceRepository:
    def __init__(self) -> None:
        self.retention_cutoff = None
        self.recovery_values = None

    def delete_expired_before(self, cutoff):
        self.retention_cutoff = cutoff
        return 4

    def recover_stale_running(self, *, cutoff, recovered_at):
        self.recovery_values = (cutoff, recovered_at)
        return 2

    def count_stale_running(self, cutoff):
        self.stale_count_cutoff = cutoff
        return 3

    def count_expired_before(self, cutoff):
        self.expired_count_cutoff = cutoff
        return 5

    def recover_and_delete(self, **values):
        self.combined_values = values
        return 3, 5


def test_explicit_retention_uses_configured_cutoff_and_returns_count() -> None:
    repository = RecordingMaintenanceRepository()
    service = ToolCallAuditMaintenanceService(
        repository, retention_days=30, stale_after_seconds=60
    )
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)

    assert service.delete_expired(now) == 4
    assert repository.retention_cutoff == now - timedelta(days=30)


def test_explicit_recovery_uses_configured_cutoff_and_returns_count() -> None:
    repository = RecordingMaintenanceRepository()
    service = ToolCallAuditMaintenanceService(
        repository, retention_days=30, stale_after_seconds=90
    )
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)

    assert service.recover_stale(now) == 2
    assert repository.recovery_values == (now - timedelta(seconds=90), now)


def test_preview_is_read_only_and_combined_uses_one_repository_operation() -> None:
    repository = RecordingMaintenanceRepository()
    service = ToolCallAuditMaintenanceService(
        repository, retention_days=30, stale_after_seconds=90
    )
    now = datetime(2026, 7, 25, tzinfo=timezone.utc)

    preview = service.preview(now)
    assert preview.stale_count == 3
    assert preview.expired_count == 5
    assert preview.stale_cutoff == now - timedelta(seconds=90)
    assert preview.retention_cutoff == now - timedelta(days=30)

    assert service.run_combined(now) == (3, 5)
    assert repository.combined_values == {
        "stale_cutoff": now - timedelta(seconds=90),
        "retention_cutoff": now - timedelta(days=30),
        "recovered_at": now,
    }


@pytest.mark.parametrize("retention,stale", [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_maintenance_configuration_must_be_positive(retention, stale) -> None:
    with pytest.raises(ValueError, match="positive"):
        ToolCallAuditMaintenanceService(
            RecordingMaintenanceRepository(),
            retention_days=retention,
            stale_after_seconds=stale,
        )


@pytest.mark.parametrize(
    "field",
    [
        "audit_payload_max_bytes",
        "tool_call_retention_days",
        "tool_call_stale_after_seconds",
    ],
)
def test_audit_settings_must_be_positive(field) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: 0})
