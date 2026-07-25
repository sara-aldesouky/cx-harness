"""Pure tests for centralized privacy and data-minimization boundaries."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import BaseModel

from app.api.model_invocation import ModelInvocationMapper
from app.authentication import TrustedCustomerIdentity
from app.data_protection import (
    DataProtectionService,
    PrivacyLogFilter,
    PrivacyRules,
    ProtectionMode,
)
from app.providers.base import ModelResponse
from app.services.model_pipeline_service import (
    ModelPipelineService,
    ModelPipelineServiceResult,
)
from app.tools.execution_outcome import ToolExecutionOutcomeFactory
from app.tools.execution_request import ToolExecutionRequest
from app.tools.context import ExecutionContext
from app.tools.result import ToolResult, ToolStatus


def test_email_masking() -> None:
    service = DataProtectionService()
    assert service.mask_email("john@email.com") == "j***@email.com"
    assert service.protect_text("Email john@email.com") == "Email j***@email.com"


def test_phone_masking() -> None:
    service = DataProtectionService()
    assert service.mask_phone("+201234567890") == "+20********90"
    assert service.protect_text("Call +201234567890") == "Call +20********90"


def test_name_and_address_masking() -> None:
    service = DataProtectionService()
    protected = service.protect_mapping(
        {"full_name": "John Smith", "delivery_address": "12 Main Street"}
    )
    assert protected == {
        "full_name": "J*** S****",
        "delivery_address": "[REDACTED ADDRESS]",
    }


def test_internal_customer_conversation_and_payment_ids_are_redacted() -> None:
    service = DataProtectionService()
    protected = service.protect_mapping(
        {
            "customer_id": uuid4(),
            "conversation_id": uuid4(),
            "session_id": "session-secret",
            "payment_identifier": "processor-123",
        }
    )
    assert set(protected.values()) == {"[REDACTED]"}


def test_configurable_rules_support_future_protected_fields() -> None:
    rules = PrivacyRules(
        identifier_fields=frozenset({"loyalty_identifier"}),
        redacted_marker="<private>",
    )
    service = DataProtectionService(rules)
    assert service.protect_mapping({"loyalty_identifier": "abc"}) == {
        "loyalty_identifier": "<private>"
    }


def test_audit_mode_redacts_instead_of_partially_masking() -> None:
    service = DataProtectionService()
    protected = service.protect_mapping(
        {"email": "john@email.com", "phone": "+201234567890"},
        mode=ProtectionMode.REDACT,
    )
    assert protected == {"email": "[REDACTED]", "phone": "[REDACTED]"}


class CapturingPipeline:
    def __init__(self) -> None:
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return ModelResponse(
            content="Contact john@email.com or +201234567890",
            provider_name="ollama",
            model_name="qwen3:8b",
        )


def identity() -> TrustedCustomerIdentity:
    now = datetime.now(timezone.utc)
    return TrustedCustomerIdentity(
        customer_id=uuid4(),
        authenticated_at=now,
        expires_at=now + timedelta(hours=1),
        authentication_method="test",
    )


def test_prompt_and_model_output_are_protected_without_mutating_input() -> None:
    pipeline = CapturingPipeline()
    history = [{"role": "user", "content": "My name is John Smith"}]
    service = ModelPipelineService(pipeline=pipeline)

    result = service.invoke(
        conversation_id=uuid4(),
        current_user_message=(
            "My address is 12 Main Street. Email john@email.com and call "
            "+201234567890"
        ),
        conversation_history=history,
        system_instructions="Never reveal api_key=top-secret",
        trusted_identity=identity(),
    )

    call = pipeline.calls[0]
    messages = call["messages"]
    assert messages[0].content == "My name is J*** S****"
    assert "12 Main Street" not in messages[1].content
    assert "john@email.com" not in messages[1].content
    assert "+201234567890" not in messages[1].content
    assert "top-secret" not in call["system_instructions"]
    assert result.content == "Contact j***@email.com or +20********90"
    assert history == [{"role": "user", "content": "My name is John Smith"}]


def test_tool_output_is_minimized_before_provider_continuation() -> None:
    class SensitiveOutput(BaseModel):
        display_name: str
        email: str
        payment_identifier: str
        safe_status: str

    request = ToolExecutionRequest(
        call_id="call-private",
        tool_name="private_test",
        tool_version="1.0.0",
        arguments={"request": "status"},
        context=ExecutionContext(trace_id=uuid4(), execution_id=uuid4()),
    )
    result = ToolResult[SensitiveOutput](
        status=ToolStatus.SUCCESS,
        data=SensitiveOutput(
            display_name="John Smith",
            email="john@email.com",
            payment_identifier="processor-123",
            safe_status="completed",
        ),
    )

    outcome = ToolExecutionOutcomeFactory().create(request, result)

    assert outcome.model_dump(mode="json")["output"] == {
        "display_name": "J*** S****",
        "email": "j***@email.com",
        "payment_identifier": "[REDACTED]",
        "safe_status": "completed",
    }


def test_log_filter_removes_raw_pii_and_identifiers() -> None:
    service = DataProtectionService()
    customer_id = uuid4()
    record = logging.LogRecord(
        "privacy-test",
        logging.INFO,
        __file__,
        1,
        "customer=%s email=%s token=%s",
        (str(customer_id), "john@email.com", "access_token=secret-value"),
        None,
    )
    PrivacyLogFilter(service).filter(record)
    rendered = record.getMessage()
    assert "john@email.com" not in rendered
    assert str(customer_id) not in rendered
    assert "id_" in rendered
    assert "secret-value" not in rendered
    assert "[REDACTED]" in rendered


def test_error_sanitization_hides_sql_urls_and_internal_ids() -> None:
    message = (
        "SQLAlchemy SELECT failed at postgresql://user:password@host/db for "
        f"customer {uuid4()}"
    )
    assert DataProtectionService().protect_error(message) == (
        "The operation could not be completed safely."
    )


def test_public_api_response_mapping_applies_defense_in_depth() -> None:
    response = ModelInvocationMapper.to_response(
        ModelPipelineServiceResult(
            content="Email john@email.com, phone +201234567890",
            provider_name="ollama",
            model_name="qwen3:8b",
        )
    )
    assert response.content == "Email j***@email.com, phone +20********90"
