"""Real FastAPI, Ollama/Qwen, and PostgreSQL endpoint verification."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.dependencies import (
    DEFAULT_MODEL_SYSTEM_INSTRUCTIONS,
    get_model_invocation_mapper,
)
from app.api.model_invocation import ModelInvocationMapper
from app.config.settings import Settings
from app.database.models import Conversation, Customer, ModelRun
from app.harness import build_model_pipeline
from app.main import app
from app.services import ModelPipelineService
from tests.models.factories import create_conversation, create_customer


pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_http_model,
    pytest.mark.skipif(
        os.getenv("RUN_HTTP_OLLAMA_INTEGRATION") != "1",
        reason=(
            "set RUN_HTTP_OLLAMA_INTEGRATION=1 to run local HTTP model verification"
        ),
    ),
]


def test_real_model_invocation_endpoint_persists_exactly_one_run(
    test_database_url,
    test_session_factory,
) -> None:
    """Exercise the public HTTP boundary and clean every disposable row."""

    with test_session_factory.begin() as session:
        customer = create_customer(
            session,
            first_name="Disposable",
            last_name="HTTP Verification",
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
    mapper = ModelInvocationMapper(
        service=ModelPipelineService(
            pipeline=pipeline,
            provider_name="ollama",
            model_name="qwen3:8b",
        ),
        default_system_instructions=DEFAULT_MODEL_SYSTEM_INSTRUCTIONS,
    )
    app.dependency_overrides[get_model_invocation_mapper] = lambda: mapper
    model_run_id = None

    try:
        with test_session_factory() as session:
            before = session.scalar(
                select(func.count())
                .select_from(ModelRun)
                .where(ModelRun.conversation_id == conversation_id)
            )
        assert before == 0

        request_json = {
            "conversation_id": str(conversation_id),
            "current_user_message": "Where is my order?",
            "conversation_history": [],
            "system_instructions": (
                "Reply in one short sentence and explain that no order data "
                "was supplied."
            ),
        }
        with TestClient(app) as client:
            response = client.post("/api/v1/model/invoke", json=request_json)

        assert response.status_code == 200
        response_json = response.json()
        assert set(response_json) == {"content", "provider_name", "model_name"}
        assert isinstance(response_json["content"], str)
        assert response_json["content"].strip()
        assert response_json["provider_name"] == "ollama"
        assert response_json["model_name"] == "qwen3:8b"
        print(f"HTTP_REQUEST={request_json}")
        print(f"HTTP_STATUS={response.status_code}")
        print(f"HTTP_RESPONSE={response_json}")

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
        app.dependency_overrides.pop(get_model_invocation_mapper, None)
        with test_session_factory.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                session.delete(conversation)
                session.flush()
            customer = session.get(Customer, customer_id)
            if customer is not None:
                session.delete(customer)

    assert model_run_id is not None
    with test_session_factory() as session:
        assert session.get(ModelRun, model_run_id) is None
        assert session.get(Conversation, conversation_id) is None
        assert session.get(Customer, customer_id) is None
    print(
        "CLEANUP="
        f"model_run={model_run_id} conversation={conversation_id} "
        f"customer={customer_id} removed"
    )
