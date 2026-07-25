"""Isolated PostgreSQL fixtures for real business-tool execution."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from app.config.settings import settings
from app.database.session import get_engine, get_session_factory


BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _dispose_cached_application_engine() -> None:
    """Dispose an existing cached engine without creating a new one."""

    get_session_factory.cache_clear()
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()


@pytest.fixture(scope="module", autouse=True)
def migrated_application_test_database(
    test_database_url: str,
    test_engine: Engine,
) -> Generator[None, None, None]:
    """Bind the real application session factory to migrated test PostgreSQL."""

    original_database_url = settings.database_url
    _dispose_cached_application_engine()
    settings.database_url = test_database_url

    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    scripts = ScriptDirectory.from_config(alembic_config)
    with test_engine.connect() as connection:
        live_revision = MigrationContext.configure(connection).get_current_revision()
    assert live_revision == scripts.get_current_head()

    try:
        yield
    finally:
        _dispose_cached_application_engine()
        settings.database_url = original_database_url
