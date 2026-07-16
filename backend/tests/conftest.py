"""Shared pytest fixtures for isolated PostgreSQL testing."""

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_test_database_url() -> str:
    """Load the dedicated test URL without falling back to development."""

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    database_url = os.getenv("DATABASE_URL_TEST", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL_TEST is required for database tests. "
            "Configure a separate PostgreSQL test database in the root .env file."
        )
    return database_url


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the explicitly configured, isolated test database URL."""

    return get_test_database_url()


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
