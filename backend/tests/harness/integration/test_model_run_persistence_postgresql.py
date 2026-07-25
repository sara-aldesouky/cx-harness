"""Real PostgreSQL verification for the ModelRun audit write boundary."""

from datetime import datetime, timedelta, timezone

import pytest

from app.database.models import Conversation, Customer, ModelRun
from app.database.repositories import ModelRunAuditRepository
from tests.models.factories import create_conversation, create_customer


@pytest.mark.integration
def test_model_run_audit_repository_persists_and_finalizes(
    test_session_factory,
) -> None:
    with test_session_factory.begin() as session:
        customer = create_customer(session)
        conversation = create_conversation(session, customer)
        customer_id = customer.id
        conversation_id = conversation.id

    repository = ModelRunAuditRepository(test_session_factory)
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    finished_at = started_at + timedelta(milliseconds=321)

    try:
        model_run_id = repository.create_running(
            conversation_id=conversation_id,
            provider="qwen",
            model_name="qwen3:8b",
            started_at=started_at,
        )
        with test_session_factory() as session:
            running = session.get(ModelRun, model_run_id)
            assert running is not None
            assert running.status == "running"
            assert running.success is False
            assert running.finished_at is None

        repository.finalize(
            model_run_id,
            status="completed",
            success=True,
            finished_at=finished_at,
            latency_ms=321,
            error_message=None,
        )
        with test_session_factory() as session:
            completed = session.get(ModelRun, model_run_id)
            assert completed is not None
            assert completed.provider == "qwen"
            assert completed.model_name == "qwen3:8b"
            assert completed.status == "completed"
            assert completed.success is True
            assert completed.started_at == started_at
            assert completed.finished_at == finished_at
            assert completed.latency_ms == 321
            assert completed.error_message is None
    finally:
        with test_session_factory.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                session.delete(conversation)
                session.flush()
            customer = session.get(Customer, customer_id)
            if customer is not None:
                session.delete(customer)
