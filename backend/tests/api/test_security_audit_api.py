"""Authentication security-event tests through the real HTTP dependency."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.api import dependencies
from app.api.dependencies import get_customer_authenticator, get_model_invocation_mapper
from app.authentication import (
    AuthenticationError,
    AuthenticationFailureCode,
    TrustedCustomerIdentity,
)
from app.main import app
from app.schemas.model_invocation import ModelInvocationResponse
from app.security_audit import SecurityEventType


class Sink:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)


class Authenticator:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error

    def authenticate(self, _credential):
        if self.error:
            raise self.error
        return self.result


class Mapper:
    def invoke(self, _request, _identity):
        return ModelInvocationResponse(
            content="safe", provider_name="ollama", model_name="qwen3:8b"
        )


def payload() -> dict:
    return {
        "conversation_id": str(uuid4()),
        "current_user_message": "Hello",
        "conversation_history": [],
    }


@pytest.fixture
def audit_sink(monkeypatch):
    sink = Sink()
    monkeypatch.setattr(dependencies.security_audit_recorder, "_sink", sink)
    return sink


def enable(authenticator) -> None:
    app.dependency_overrides.pop(dependencies.get_authenticated_customer_identity, None)
    app.dependency_overrides[get_customer_authenticator] = lambda: authenticator
    app.dependency_overrides[get_model_invocation_mapper] = lambda: Mapper()


def test_successful_authentication_records_pseudonymous_event(api_client, audit_sink) -> None:
    now = datetime.now(timezone.utc)
    customer_id = uuid4()
    enable(
        Authenticator(
            result=TrustedCustomerIdentity(
                customer_id=customer_id,
                authenticated_at=now,
                expires_at=now + timedelta(hours=1),
                authentication_method="test",
            )
        )
    )

    response = api_client.post(
        "/api/v1/model/invoke",
        json=payload(),
        headers={"Authorization": "Bearer opaque", "X-Request-ID": str(uuid4())},
    )

    assert response.status_code == 200
    event = next(
        event
        for event in audit_sink.events
        if event.event_type is SecurityEventType.AUTHENTICATION_SUCCEEDED
    )
    assert event.customer_pseudonym.startswith("psn_")
    assert str(customer_id) not in event.model_dump_json()


@pytest.mark.parametrize(
    ("code", "event_type"),
    [
        (AuthenticationFailureCode.INVALID_IDENTITY, SecurityEventType.INVALID_CREDENTIALS),
        (AuthenticationFailureCode.EXPIRED_AUTHENTICATION, SecurityEventType.CREDENTIALS_EXPIRED),
        (AuthenticationFailureCode.MISSING_IDENTITY, SecurityEventType.AUTHENTICATION_FAILED),
    ],
)
def test_failed_authentication_records_safe_event(api_client, audit_sink, code, event_type) -> None:
    enable(Authenticator(error=AuthenticationError(code, "Safe failure.")))
    response = api_client.post("/api/v1/model/invoke", json=payload())
    assert response.status_code == 401
    assert any(event.event_type is event_type for event in audit_sink.events)
    assert "Bearer" not in "".join(event.model_dump_json() for event in audit_sink.events)
