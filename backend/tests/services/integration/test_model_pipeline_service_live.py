"""Real local Ollama and PostgreSQL verification through the application service."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.config.settings import Settings
from app.authentication import TrustedCustomerIdentity
from app.database.models import Conversation, Customer, ModelRun
from app.harness import build_model_pipeline
from app.services import ModelPipelineService, ModelPipelineServiceResult
from tests.models.factories import create_conversation, create_customer


pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_model,
    pytest.mark.skipif(
        os.getenv("RUN_OLLAMA_INTEGRATION") != "1",
        reason="set RUN_OLLAMA_INTEGRATION=1 to run local Ollama verification",
    ),
]


def test_real_application_service_persists_exactly_one_model_run(
    test_database_url,
    test_session_factory,
) -> None:
    """Exercise every Stage 7 layer and remove all disposable rows afterward."""

    with test_session_factory.begin() as session:
        customer = create_customer(
            session,
            first_name="Disposable",
            last_name="Pipeline Verification",
        )
        conversation = create_conversation(
            session,
            customer,
            channel="internal_test",
            active_model="qwen3:8b",
        )
        customer_id = customer.id
        conversation_id = conversation.id

    pipeline = build_model_pipeline(
        app_settings=Settings(
            database_url=test_database_url,
            ollama_base_url="http://localhost:11434",
            ollama_model_name="qwen3:8b",
            ollama_connect_timeout_seconds=2.0,
            ollama_read_timeout_seconds=60.0,
        ),
        database_session_factory=test_session_factory,
    )
    service = ModelPipelineService(
        pipeline=pipeline,
        provider_name="ollama",
        model_name="qwen3:8b",
    )

    try:
        with test_session_factory() as session:
            before = session.scalar(
                select(func.count())
                .select_from(ModelRun)
                .where(ModelRun.conversation_id == conversation_id)
            )
        assert before == 0

        result = service.invoke(
            conversation_id=conversation_id,
            current_user_message="Where is my order?",
            conversation_history=(),
            system_instructions=(
                "Reply in one short sentence and explain that no order data "
                "was supplied."
            ),
            trusted_identity=TrustedCustomerIdentity(
                customer_id=customer_id,
                authenticated_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                authentication_method="live_test",
            ),
        )

        assert isinstance(result, ModelPipelineServiceResult)
        assert result.content.strip()
        assert result.provider_name == "ollama"
        assert result.model_name == "qwen3:8b"
        print(f"SERVICE_RESULT={result.model_dump_json()}")

        with test_session_factory() as session:
            records = list(
                session.scalars(
                    select(ModelRun).where(
                        ModelRun.conversation_id == conversation_id
                    )
                )
            )
            assert len(records) == 1
            model_run = records[0]
            model_run_id = model_run.id
            assert model_run.conversation_id == conversation_id
            assert model_run.provider == "qwen"
            assert model_run.model_name == "qwen3:8b"
            assert model_run.status == "completed"
            assert model_run.success is True
            assert model_run.started_at is not None
            assert model_run.finished_at is not None
            assert model_run.finished_at >= model_run.started_at
            assert model_run.latency_ms is not None
            assert model_run.latency_ms >= 0
            assert model_run.error_message is None
            print(
                "MODEL_RUN="
                f"id={model_run_id} "
                f"conversation_id={model_run.conversation_id} "
                f"provider={model_run.provider} "
                f"model={model_run.model_name} "
                f"status={model_run.status} "
                f"success={model_run.success} "
                f"started_at={model_run.started_at.isoformat()} "
                f"finished_at={model_run.finished_at.isoformat()} "
                f"latency_ms={model_run.latency_ms}"
            )
    finally:
        with test_session_factory.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                session.delete(conversation)
                session.flush()
            customer = session.get(Customer, customer_id)
            if customer is not None:
                session.delete(customer)

    with test_session_factory() as session:
        assert session.get(ModelRun, model_run_id) is None
        assert session.get(Conversation, conversation_id) is None
        assert session.get(Customer, customer_id) is None
    print(
        "CLEANUP="
        f"model_run={model_run_id} conversation={conversation_id} "
        f"customer={customer_id} removed"
    )
