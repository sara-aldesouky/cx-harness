"""Repository-test isolation and query-inspection fixtures."""

from collections.abc import Generator
from contextlib import contextmanager

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.database.models import Customer, Order, OrderItem


READ_ONLY_TABLES = (Customer, Order, OrderItem)


def table_counts(session: Session) -> dict[str, int]:
    """Return counts for every table exposed by the commerce repositories."""

    return {
        model.__tablename__: session.scalar(
            select(func.count()).select_from(model)
        )
        or 0
        for model in READ_ONLY_TABLES
    }


@pytest.fixture
def repository_session(test_engine: Engine) -> Generator[Session, None, None]:
    """Run a repository test in a transaction and prove cleanup by rollback."""

    with Session(test_engine) as verification_session:
        counts_before = table_counts(verification_session)
    assert counts_before == {"customers": 0, "orders": 0, "order_items": 0}

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

        with Session(test_engine) as verification_session:
            assert table_counts(verification_session) == counts_before


@pytest.fixture
def count_queries(test_engine: Engine):
    """Count SQL statements inside a narrowly scoped assertion block."""

    @contextmanager
    def counter():
        statements = []

        def record_statement(
            connection, cursor, statement, parameters, context, executemany
        ):
            statements.append(statement)

        event.listen(test_engine, "before_cursor_execute", record_statement)
        try:
            yield statements
        finally:
            event.remove(test_engine, "before_cursor_execute", record_statement)

    return counter
