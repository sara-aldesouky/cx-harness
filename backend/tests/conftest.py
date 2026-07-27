"""Shared pytest fixtures for isolated PostgreSQL testing."""

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values, load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_test_database_url() -> str:
    """Load and strongly validate the dedicated PostgreSQL test URL."""

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    database_url = os.getenv("DATABASE_URL_TEST", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL_TEST is required for database tests. "
            "Configure a separate PostgreSQL test database in the root .env file."
        )

    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise RuntimeError("DATABASE_URL_TEST must use PostgreSQL.")

    database_name = (parsed_url.database or "").lower()
    username = (parsed_url.username or "").lower()
    if "test" not in database_name or "test" not in username:
        raise RuntimeError(
            "DATABASE_URL_TEST must use a database and username containing 'test'."
        )

    hostname = (parsed_url.host or "").lower()
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(
            "DATABASE_URL_TEST must target local PostgreSQL; remote hosts are blocked."
        )

    dotenv_database_url = str(
        dotenv_values(PROJECT_ROOT / ".env").get("DATABASE_URL", "")
    ).strip()
    configured_development_urls = {
        value
        for value in (os.getenv("DATABASE_URL", "").strip(), dotenv_database_url)
        if value
    }
    if database_url in configured_development_urls:
        raise RuntimeError(
            "DATABASE_URL_TEST must be different from the development DATABASE_URL."
        )
    return database_url


@pytest.fixture(scope="session")
def test_database_url() -> Generator[str, None, None]:
    """Create one disposable migrated database for this pytest session."""

    configured_url = make_url(get_test_database_url())
    database_name = f"{configured_url.database}_pytest_{uuid4().hex[:12]}"
    if len(database_name) > 63:
        database_name = f"cx_test_pytest_{uuid4().hex[:12]}"
    session_url = configured_url.set(database=database_name)
    maintenance_url = configured_url.set(database="postgres")
    maintenance_engine = create_engine(
        maintenance_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    with maintenance_engine.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

    environment = {
        **os.environ,
        "DATABASE_URL": session_url.render_as_string(hide_password=False),
    }
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "heads"],
            cwd=PROJECT_ROOT / "backend",
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        yield session_url.render_as_string(hide_password=False)
    finally:
        with maintenance_engine.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{database_name}' AND pid <> pg_backend_pid()"
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        maintenance_engine.dispose()


@pytest.fixture(scope="session")
def test_engine(test_database_url: str) -> Generator[Engine, None, None]:
    """Provide an engine connected only to the dedicated test database."""

    engine = create_engine(test_database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def test_session_factory(
    test_engine: Engine,
) -> sessionmaker[Session]:
    """Provide a reusable test-session factory."""

    return sessionmaker(
        bind=test_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


@pytest.fixture
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    """Provide a session whose transaction is rolled back after each test."""

    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
