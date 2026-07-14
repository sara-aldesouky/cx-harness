"""SQLAlchemy engine and session lifecycle configuration."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings


class DatabaseConfigurationError(RuntimeError):
    """Raised when the database connection settings are incomplete."""


@lru_cache
def get_engine() -> Engine:
    """Create and cache the application's SQLAlchemy engine."""

    database_url = settings.database_url.strip()
    if not database_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is not configured. Add the Render PostgreSQL URL to .env."
        )

    return create_engine(database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create and cache the application's database session factory."""

    return sessionmaker(
        bind=get_engine(),
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def get_database_session() -> Generator[Session, None, None]:
    """Provide a session and guarantee that it is closed after use."""

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
