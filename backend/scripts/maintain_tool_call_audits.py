"""Explicit operator command for ToolCall audit maintenance."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import Optional, TextIO

from sqlalchemy.exc import SQLAlchemyError

from app.config.settings import settings
from app.database.repositories import ToolCallAuditRepository
from app.database.session import get_session_factory
from app.services import (
    DatabaseTarget,
    DatabaseTargetClassification,
    ToolCallAuditMaintenanceService,
    classify_database_target,
)


OPERATIONS = ("dry-run", "recover", "cleanup", "combined")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicitly maintain ToolCall audit records."
    )
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation for cleanup or combined mode.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Explicitly permit writes to a classified production target.",
    )
    parser.add_argument(
        "--allow-unknown-target",
        action="store_true",
        help="Explicitly permit writes to an unknown database target.",
    )
    return parser


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    service: Optional[ToolCallAuditMaintenanceService] = None,
    target: Optional[DatabaseTarget] = None,
    input_fn: Callable[[str], str] = input,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Parse arguments, coordinate existing services, and return an exit code."""

    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    arguments = build_parser().parse_args(argv)

    try:
        database_target = target or classify_database_target(
            settings.database_url,
            settings.environment,
        )
        _print_database_target(output, database_target)

        is_write = arguments.operation != "dry-run"
        if is_write and not _write_target_is_allowed(
            arguments, database_target, errors
        ):
            return 2
        if is_write:
            acknowledgement = input_fn(
                f"Type database name '{database_target.database}' to authorize "
                "this write operation: "
            )
            if acknowledgement.strip() != database_target.database:
                print(
                    "Database acknowledgement failed; no writes were performed.",
                    file=output,
                )
                return 2

        maintenance = service or ToolCallAuditMaintenanceService(
            ToolCallAuditRepository(get_session_factory())
        )
        preview = maintenance.preview()

        if arguments.operation == "dry-run":
            print("Audit Maintenance Dry Run", file=output)
            print(
                f"Stale executions that would be recovered: {preview.stale_count}",
                file=output,
            )
            print(
                f"Expired audit records that would be deleted: "
                f"{preview.expired_count}",
                file=output,
            )
            if preview.stale_count == 0 and preview.expired_count == 0:
                print("No audit maintenance is required.", file=output)
            print("Dry run only; no database records were changed.", file=output)
            return 0

        if (
            arguments.operation in {"cleanup", "combined"}
            and preview.expired_count > 0
            and not arguments.force
        ):
            answer = input_fn(
                f"Delete {preview.expired_count} expired audit record(s)? "
                "Type 'yes' to continue: "
            )
            if answer.strip().casefold() != "yes":
                print("Cleanup cancelled; no maintenance was performed.", file=output)
                return 2

        recovered = 0
        deleted = 0
        if arguments.operation == "recover":
            recovered = maintenance.recover_stale()
        elif arguments.operation == "cleanup":
            deleted = maintenance.delete_expired()
        else:
            recovered, deleted = maintenance.run_combined()

        remaining = maintenance.preview()
        _print_summary(
            output,
            recovered,
            deleted,
            remaining_stale=remaining.stale_count,
            retention_cutoff=preview.retention_cutoff.isoformat(),
        )
        if recovered == 0 and deleted == 0:
            print("No audit maintenance was required.", file=output)
        print("Completed successfully.", file=output)
        return 0
    except ValueError as error:
        print(f"Invalid audit maintenance configuration: {error}", file=errors)
        return 2
    except SQLAlchemyError as error:
        print(
            f"Audit maintenance database failure: {type(error).__name__}",
            file=errors,
        )
        return 1
    except Exception as error:
        print(f"Audit maintenance failed: {type(error).__name__}: {error}", file=errors)
        return 1


def _print_summary(
    output: TextIO,
    recovered: int,
    deleted: int,
    *,
    remaining_stale: Optional[int] = None,
    retention_cutoff: Optional[str] = None,
) -> None:
    print("Audit Maintenance Summary", file=output)
    print(f"Recovered stale executions: {recovered}", file=output)
    print(f"Deleted expired audit records: {deleted}", file=output)
    if remaining_stale is not None:
        print(f"Remaining stale executions: {remaining_stale}", file=output)
    if retention_cutoff is not None:
        print(f"Retention cutoff: {retention_cutoff}", file=output)


def _print_database_target(output: TextIO, target: DatabaseTarget) -> None:
    print("Database Target", file=output)
    print(f"Classification: {target.classification.value}", file=output)
    print(f"Host: {target.host}", file=output)
    print(f"Database: {target.database}", file=output)
    print(f"Environment: {target.environment}", file=output)


def _write_target_is_allowed(
    arguments: argparse.Namespace,
    target: DatabaseTarget,
    errors: TextIO,
) -> bool:
    if (
        target.classification is DatabaseTargetClassification.PRODUCTION
        and not arguments.allow_production
    ):
        print(
            "Production write blocked. Re-run with --allow-production to proceed.",
            file=errors,
        )
        return False
    if (
        target.classification is DatabaseTargetClassification.UNKNOWN
        and not arguments.allow_unknown_target
    ):
        print(
            "Unknown-target write blocked. Re-run with "
            "--allow-unknown-target to proceed.",
            file=errors,
        )
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
