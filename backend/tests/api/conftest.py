"""API integration fixtures isolated from the Render database."""

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.models.factories import (
    create_conversation,
    create_customer,
    create_message,
    create_model_run,
    create_order,
    create_order_item,
)
from tests.repositories.conftest import table_counts


RENDER_SENTINEL = "postgresql://blocked:blocked@127.0.0.1:1/render_must_not_be_used"
os.environ["DATABASE_URL"] = RENDER_SENTINEL

from app.api.dependencies import get_db_session  # noqa: E402
from app.config.settings import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def block_render_database() -> None:
    """Prove the application configuration cannot resolve to Render in API tests."""

    assert settings.database_url == RENDER_SENTINEL


@pytest.fixture
def api_session(test_engine) -> Generator[Session, None, None]:
    """Provide a rollback-controlled session and prove table counts are restored."""

    with Session(test_engine) as verification_session:
        counts_before = table_counts(verification_session)

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
def api_client(api_session: Session) -> Generator[TestClient, None, None]:
    """Use the test transaction for every FastAPI database dependency."""

    def override_database_session():
        yield api_session

    app.dependency_overrides[get_db_session] = override_database_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def api_data(api_session: Session) -> dict:
    """Create a compact graph shared by read-only API tests."""

    customer = create_customer(
        api_session,
        first_name="Alpha",
        last_name="Customer",
        email="alpha@example.test",
        phone="+201000000001",
    )
    other_customer = create_customer(
        api_session,
        first_name="Beta",
        last_name="Customer",
        email="beta@example.test",
        phone="+201000000002",
    )
    order = create_order(
        api_session,
        customer,
        order_number="API-ORDER-001",
        status="delivered",
        payment_status="paid",
    )
    other_order = create_order(
        api_session,
        other_customer,
        order_number="API-ORDER-002",
        status="pending",
        payment_status="pending",
    )
    item = create_order_item(api_session, order, item_status="included")
    other_item = create_order_item(api_session, other_order, item_status="missing")
    conversation = create_conversation(
        api_session, customer, order, status="open", channel="web"
    )
    other_conversation = create_conversation(
        api_session,
        other_customer,
        other_order,
        status="closed",
        channel="mobile",
    )
    first_message = create_message(
        api_session,
        conversation,
        role="user",
        language="english",
        sequence_number=1,
    )
    second_message = create_message(
        api_session,
        conversation,
        role="assistant",
        content="تمام, your order was delivered.",
        language="mixed",
        sequence_number=2,
    )
    create_message(api_session, other_conversation, sequence_number=1)
    model_run = create_model_run(api_session, conversation)
    failed_run = create_model_run(
        api_session,
        other_conversation,
        provider="qwen",
        model_name="qwen-test",
        status="failed",
        success=False,
        error_message="Synthetic failure",
    )
    return {
        "customer": customer,
        "other_customer": other_customer,
        "order": order,
        "other_order": other_order,
        "item": item,
        "other_item": other_item,
        "conversation": conversation,
        "other_conversation": other_conversation,
        "first_message": first_message,
        "second_message": second_message,
        "model_run": model_run,
        "failed_run": failed_run,
    }
