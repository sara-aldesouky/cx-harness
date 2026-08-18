"""Stage 13.4 session-scoped adapter for the frozen order resolver boundary."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.database.repositories.order_repository import OrderRepository
from app.entity_resolution import ExistingOrderRepositoryAdapter, OrderResolutionRecord


class SessionFactoryOrderResolutionRepository:
    """Open one short-lived SQLAlchemy session per resolver repository call."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory

    def find_for_customer(
        self, customer_id: UUID, order_number: str
    ) -> Optional[OrderResolutionRecord]:
        with self._session_factory() as session:
            return ExistingOrderRepositoryAdapter(
                OrderRepository(session)
            ).find_for_customer(customer_id, order_number)

    def list_active_for_customer(
        self, customer_id: UUID
    ) -> tuple[OrderResolutionRecord, ...]:
        with self._session_factory() as session:
            return ExistingOrderRepositoryAdapter(
                OrderRepository(session)
            ).list_active_for_customer(customer_id)

    def latest_for_customer(
        self, customer_id: UUID
    ) -> Optional[OrderResolutionRecord]:
        with self._session_factory() as session:
            return ExistingOrderRepositoryAdapter(
                OrderRepository(session)
            ).latest_for_customer(customer_id)
