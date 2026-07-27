"""Upgrade/downgrade verification against the guarded local PostgreSQL database."""

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import inspect


pytestmark = pytest.mark.integration
BACKEND = Path(__file__).resolve().parents[3]
REVISION = "b2aa96d282d0"
PARENT = "d7816236ae9e"
TABLES = {
    "benchmark_suites", "benchmark_runs", "benchmark_conversation_results",
    "benchmark_provider_turns", "benchmark_tool_executions",
    "benchmark_metric_results", "benchmark_failure_events",
}


def alembic(database_url: str, *arguments: str) -> None:
    environment = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        [str(BACKEND / ".venv/bin/python"), "-m", "alembic", *arguments],
        cwd=BACKEND, env=environment, check=True, capture_output=True, text=True,
    )


def test_benchmark_analytics_migration_downgrades_and_upgrades_cleanly(
    test_database_url, test_engine
):
    alembic(test_database_url, "downgrade", PARENT)
    try:
        assert TABLES.isdisjoint(inspect(test_engine).get_table_names())
        alembic(test_database_url, "upgrade", REVISION)
        assert TABLES <= set(inspect(test_engine).get_table_names())
    finally:
        alembic(test_database_url, "upgrade", "heads")
