"""Database-independent transaction contract and SQLAlchemy adapter."""

from __future__ import annotations

from typing import Callable, Generic, Protocol, TypeVar

from sqlalchemy.orm import Session, sessionmaker


TransactionT = TypeVar("TransactionT")
ResultT = TypeVar("ResultT")


class WriteTransactionError(RuntimeError):
    """Safe infrastructure failure raised after automatic rollback."""

    public_message = "The requested change could not be completed."


class TransactionManager(Protocol, Generic[TransactionT]):
    """Execute a callback exactly once within a centrally owned transaction."""

    def execute(self, callback: Callable[[TransactionT], ResultT]) -> ResultT: ...


class SQLAlchemyTransactionManager:
    """Commit on successful callback completion and roll back on exceptions."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        if not callable(getattr(session_factory, "begin", None)):
            raise TypeError("session_factory must provide begin()")
        self._session_factory = session_factory

    def execute(self, callback: Callable[[Session], ResultT]) -> ResultT:
        if not callable(callback):
            raise TypeError("transaction callback must be callable")
        try:
            with self._session_factory.begin() as session:
                return callback(session)
        except WriteTransactionError:
            raise
        except Exception as error:
            raise WriteTransactionError(
                WriteTransactionError.public_message
            ) from error
