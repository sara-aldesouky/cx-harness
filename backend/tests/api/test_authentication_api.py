"""HTTP authentication gate tests independent of providers and PostgreSQL."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.api.dependencies import (
    get_authenticated_customer_identity,
    get_customer_authenticator,
    get_model_invocation_mapper,
)
from app.authentication import (
    AuthenticationError,
    AuthenticationFailureCode,
    TrustedCustomerIdentity,
)
from app.main import app
from app.schemas.model_invocation import ModelInvocationResponse


class FakeAuthenticator:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.credentials = []

    def authenticate(self, credential):
        self.credentials.append(credential)
        if self.error:
            raise self.error
        return self.result


class CapturingMapper:
    def __init__(self) -> None:
        self.calls = []

    def invoke(self, request, identity):
        self.calls.append((request, identity))
        return ModelInvocationResponse(
            content="authenticated",
            provider_name="ollama",
            model_name="qwen3:8b",
        )


def request_payload() -> dict:
    return {
        "conversation_id": str(uuid4()),
        "current_user_message": "Where is my order?",
        "conversation_history": [],
    }


def enable_auth_dependency(authenticator, mapper) -> None:
    app.dependency_overrides.pop(get_authenticated_customer_identity, None)
    app.dependency_overrides[get_customer_authenticator] = lambda: authenticator
    app.dependency_overrides[get_model_invocation_mapper] = lambda: mapper


def test_successful_authentication_propagates_trusted_identity(api_client) -> None:
    now = datetime.now(timezone.utc)
    trusted = TrustedCustomerIdentity(
        customer_id=uuid4(),
        authenticated_at=now,
        expires_at=now + timedelta(hours=1),
        authentication_method="test",
    )
    authenticator = FakeAuthenticator(result=trusted)
    mapper = CapturingMapper()
    enable_auth_dependency(authenticator, mapper)

    response = api_client.post(
        "/api/v1/model/invoke",
        json=request_payload(),
        headers={"Authorization": "Bearer opaque"},
    )

    assert response.status_code == 200
    assert authenticator.credentials == ["Bearer opaque"]
    assert len(mapper.calls) == 1
    assert mapper.calls[0][1] is trusted


def test_missing_identity_blocks_mapper(api_client) -> None:
    authenticator = FakeAuthenticator(
        error=AuthenticationError(
            AuthenticationFailureCode.MISSING_IDENTITY,
            "Authentication credentials are required.",
        )
    )
    mapper = CapturingMapper()
    enable_auth_dependency(authenticator, mapper)

    response = api_client.post("/api/v1/model/invoke", json=request_payload())

    assert response.status_code == 401
    assert response.json() == {
        "code": "missing_identity",
        "message": "Authentication credentials are required.",
    }
    assert mapper.calls == []


def test_invalid_and_expired_identity_are_safe_401_failures(api_client) -> None:
    mapper = CapturingMapper()
    for code, message in (
        (AuthenticationFailureCode.INVALID_IDENTITY, "Authentication credentials are invalid."),
        (AuthenticationFailureCode.EXPIRED_AUTHENTICATION, "Authentication credentials have expired."),
    ):
        enable_auth_dependency(
            FakeAuthenticator(error=AuthenticationError(code, message)), mapper
        )
        response = api_client.post(
            "/api/v1/model/invoke",
            json=request_payload(),
            headers={"Authorization": "Bearer hidden"},
        )
        assert response.status_code == 401
        assert response.json() == {"code": code.value, "message": message}
        assert "hidden" not in response.text
    assert mapper.calls == []


def test_authentication_unavailable_is_safe_503(api_client) -> None:
    mapper = CapturingMapper()
    enable_auth_dependency(
        FakeAuthenticator(
            error=AuthenticationError(
                AuthenticationFailureCode.AUTHENTICATION_UNAVAILABLE,
                "Authentication is temporarily unavailable.",
            )
        ),
        mapper,
    )

    response = api_client.post(
        "/api/v1/model/invoke",
        json=request_payload(),
        headers={"Authorization": "Bearer hidden"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "authentication_unavailable"
    assert mapper.calls == []


def test_openapi_declares_customer_bearer_authentication(api_client) -> None:
    schema = api_client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/model/invoke"]["post"]

    assert operation["security"] == [{"CustomerBearerAuth": []}]
    assert schema["components"]["securitySchemes"]["CustomerBearerAuth"] == {
        "type": "http",
        "description": "Signed customer identity assertion",
        "scheme": "bearer",
    }
