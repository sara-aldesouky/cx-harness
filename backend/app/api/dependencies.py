"""Shared API dependencies."""

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.database.session import get_database_session


def get_db_session() -> Generator[Session, None, None]:
    """Provide one existing application database session per request."""

    yield from get_database_session()
