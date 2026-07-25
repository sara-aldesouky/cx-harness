"""Explicit, unscheduled ToolCall retention and recovery operations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config.settings import settings
from app.database.repositories import ToolCallAuditRepository


@dataclass(frozen=True)
class AuditMaintenancePreview:
    """Read-only maintenance counts and their calculated cutoffs."""

    stale_count: int
    expired_count: int
    stale_cutoff: datetime
    retention_cutoff: datetime


class ToolCallAuditMaintenanceService:
    """Calculate configured cutoffs and invoke narrow audit maintenance."""

    def __init__(
        self,
        repository: ToolCallAuditRepository,
        *,
        retention_days: Optional[int] = None,
        stale_after_seconds: Optional[int] = None,
    ) -> None:
        self._repository = repository
        self._retention_days = (
            settings.tool_call_retention_days
            if retention_days is None
            else retention_days
        )
        self._stale_after_seconds = (
            settings.tool_call_stale_after_seconds
            if stale_after_seconds is None
            else stale_after_seconds
        )
        if self._retention_days <= 0 or self._stale_after_seconds <= 0:
            raise ValueError("audit maintenance settings must be positive")

    def delete_expired(self, now: Optional[datetime] = None) -> int:
        """Explicitly delete audit rows older than the configured retention."""

        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(days=self._retention_days)
        return self._repository.delete_expired_before(cutoff)

    def recover_stale(self, now: Optional[datetime] = None) -> int:
        """Explicitly recover running rows older than the configured threshold."""

        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(seconds=self._stale_after_seconds)
        return self._repository.recover_stale_running(
            cutoff=cutoff,
            recovered_at=current,
        )

    def preview(self, now: Optional[datetime] = None) -> AuditMaintenancePreview:
        """Report maintenance candidates without performing writes."""

        current = now or datetime.now(timezone.utc)
        stale_cutoff = current - timedelta(seconds=self._stale_after_seconds)
        retention_cutoff = current - timedelta(days=self._retention_days)
        return AuditMaintenancePreview(
            stale_count=self._repository.count_stale_running(stale_cutoff),
            expired_count=self._repository.count_expired_before(retention_cutoff),
            stale_cutoff=stale_cutoff,
            retention_cutoff=retention_cutoff,
        )

    def run_combined(self, now: Optional[datetime] = None) -> tuple[int, int]:
        """Atomically recover stale rows and delete expired audit records."""

        current = now or datetime.now(timezone.utc)
        return self._repository.recover_and_delete(
            stale_cutoff=current - timedelta(seconds=self._stale_after_seconds),
            retention_cutoff=current - timedelta(days=self._retention_days),
            recovered_at=current,
        )
