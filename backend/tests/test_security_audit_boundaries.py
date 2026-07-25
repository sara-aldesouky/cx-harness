"""Security events emitted by real privacy and authorization boundaries."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.authentication import TrustedCustomerIdentity
from app.authorization import OwnershipAuthorizationService, OwnershipStatus
from app.identity_roles import PrincipalRole
from app.providers.base import ModelResponse
from app.role_policy import CapabilityRolePolicyService
from app.security_audit import SecurityAuditRecorder, SecurityEventType
from app.services.model_pipeline_service import ModelPipelineService
from app.tool_authorization import (
    CentralToolAuthorizationService,
    ToolPolicyRegistry,
)
from app.tools.context import ExecutionContext
from app.tools.execution_gateway import SingleToolExecutionGateway
from app.tools.execution_request import ToolExecutionRequest
from app.tools.executor import ToolExecutor
from app.tools.get_order_status import GetOrderStatusTool
from app.tools.ping import PingTool
from app.tools.registry import ToolNotFoundError, ToolRegistry
from tests.tools.audit_fakes import RecordingAuditRepository


class Sink:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)


class OwnershipResolver:
    def order_status(self, _customer_id, _reference):
        return OwnershipStatus.NOT_OWNED


def audit_pair():
    sink = Sink()
    return (
        SecurityAuditRecorder("boundary-audit-key-with-at-least-32-characters", sink),
        sink,
    )


def registry_for(tool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def request(tool_name="get_order_status", role="customer") -> ToolExecutionRequest:
    return ToolExecutionRequest(
        call_id="call-security",
        tool_name=tool_name,
        tool_version="1.0.0",
        arguments=(
            {"message": "hello"}
            if tool_name == "ping"
            else {"order_number": "ORD-10025"}
        ),
        context=ExecutionContext(
            trace_id=uuid4(),
            execution_id=uuid4(),
            conversation_id=uuid4(),
            customer_id=uuid4(),
            principal_role=role,
        ),
    )


def test_role_policy_denial_records_event_without_tool_audit() -> None:
    tools = registry_for(GetOrderStatusTool)
    security, sink = audit_pair()
    tool_audit = RecordingAuditRepository()
    gateway = SingleToolExecutionGateway(
        tools,
        ToolExecutor(tools, tool_audit),
        role_policy_service=CapabilityRolePolicyService(
            {PrincipalRole.CUSTOMER: frozenset()}
        ),
        security_audit=security,
    )
    gateway.execute(request())
    assert sink.events[-1].event_type is SecurityEventType.ROLE_POLICY_DENIED
    assert tool_audit.started == []


def test_tool_authorization_denial_records_event() -> None:
    tools = registry_for(PingTool)
    security, sink = audit_pair()
    gateway = SingleToolExecutionGateway(
        tools,
        ToolExecutor(tools, RecordingAuditRepository()),
        tool_authorization_service=CentralToolAuthorizationService(
            ToolPolicyRegistry.for_runtime(tools)
        ),
        security_audit=security,
    )
    gateway.execute(request("ping"))
    assert sink.events[-1].event_type is SecurityEventType.TOOL_AUTHORIZATION_DENIED


def test_ownership_denial_records_event() -> None:
    tools = registry_for(GetOrderStatusTool)
    security, sink = audit_pair()
    gateway = SingleToolExecutionGateway(
        tools,
        ToolExecutor(tools, RecordingAuditRepository()),
        authorization_service=OwnershipAuthorizationService(OwnershipResolver()),
        security_audit=security,
    )
    gateway.execute(request())
    assert sink.events[-1].event_type is SecurityEventType.OWNERSHIP_DENIED


def test_unknown_tool_attempt_records_event_and_preserves_existing_failure() -> None:
    tools = ToolRegistry()
    security, sink = audit_pair()
    gateway = SingleToolExecutionGateway(
        tools,
        ToolExecutor(tools, RecordingAuditRepository()),
        security_audit=security,
    )
    with pytest.raises(ToolNotFoundError):
        gateway.execute(request("unknown_tool"))
    assert sink.events[-1].event_type is SecurityEventType.UNKNOWN_TOOL_ATTEMPT


def test_invalid_role_escalation_attempt_records_security_event() -> None:
    tools = registry_for(GetOrderStatusTool)
    security, sink = audit_pair()
    gateway = SingleToolExecutionGateway(
        tools,
        ToolExecutor(tools, RecordingAuditRepository()),
        role_policy_service=CapabilityRolePolicyService(),
        security_audit=security,
    )
    gateway.execute(request(role="administrator-plus"))
    assert sink.events[-1].event_type is SecurityEventType.INVALID_ROLE_ESCALATION
    assert sink.events[-1].trusted_role is None


def test_prompt_and_unsafe_output_privacy_events(monkeypatch) -> None:
    from app.services import model_pipeline_service as module

    sink = Sink()
    monkeypatch.setattr(module.security_audit_recorder, "_sink", sink)

    class Pipeline:
        def run(self, **_kwargs):
            return ModelResponse(
                content="Email john@email.com",
                provider_name="ollama",
                model_name="qwen3:8b",
            )

    now = datetime.now(timezone.utc)
    service = ModelPipelineService(pipeline=Pipeline())
    service.invoke(
        conversation_id=uuid4(),
        current_user_message="My phone is +201234567890",
        system_instructions="Be safe.",
        trusted_identity=TrustedCustomerIdentity(
            customer_id=uuid4(),
            authenticated_at=now,
            expires_at=now + timedelta(hours=1),
            authentication_method="test",
        ),
    )
    event_types = {event.event_type for event in sink.events}
    assert SecurityEventType.PROMPT_SANITIZED in event_types
    assert SecurityEventType.UNSAFE_OUTPUT_BLOCKED in event_types
