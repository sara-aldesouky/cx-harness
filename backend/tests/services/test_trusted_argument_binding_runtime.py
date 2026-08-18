"""Stage 13.4 integration tests for bind-before-validate runtime ordering."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
from uuid import UUID, uuid4

import pytest

from app.authorization import AuthorizationDecision
from app.argument_binding import TrustedArgumentBinder
from app.conversation_state import (
    ConversationState,
    ConversationStateExpiredError,
    ConversationStateService,
    InMemoryConversationStateStore,
    StateStatus,
)
from app.entity_resolution.contracts import EntityResolutionResult, ResolutionStatus
from app.services.trusted_argument_binding_runtime import (
    InvalidTrustedSelectionRuntimeInputError,
    TrustedArgumentBindingRejected,
    TrustedSelectionPipeline,
    build_runtime_binding_policy_registry,
    validate_runtime_binding_configuration,
)
from app.tools.context import ExecutionContext
from app.tools.ping import PingTool
from app.tools.registry import ToolRegistry
from app.tools.selection import ToolSelectionRequest, ToolSelectionResolver
from app.tools.write_capabilities import WRITE_TOOL_CLASSES
from app.services.model_tool_loop_service import BoundedModelToolLoopService
from app.role_policy import RolePolicyDecision
from app.tool_authorization import ToolAuthorizationDecision
from app.tools.continuation_adapter import MockProviderContinuationAdapter
from app.tools.continuation_adapter_registry import ProviderContinuationAdapterRegistry
from app.tools.result import ToolResult, ToolStatus
from app.tools.tool_runtime import build_tool_continuation_runtime
from app.tools.write_capabilities import CancelOrderTool, WriteToolOutput
from tests.tools.audit_fakes import RecordingAuditRepository


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000001")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000002")


def context(**updates) -> ExecutionContext:
    values = {
        "trace_id": uuid4(),
        "execution_id": uuid4(),
        "conversation_id": CONVERSATION_ID,
        "customer_id": CUSTOMER_ID,
        "model_name": "test-model",
    }
    values.update(updates)
    return ExecutionContext(**values)


def resolved(order_number: str = "ORD-10025") -> EntityResolutionResult:
    return EntityResolutionResult(
        status=ResolutionStatus.RESOLVED,
        resolved_entity={
            "entity_type": "order",
            "public_reference": order_number,
            "relationship": "selected",
            "verification_source": "repository_lookup",
            "verified_at": NOW,
        },
        public_message="resolved",
    )


class RecordingResolver:
    def __init__(self, result: EntityResolutionResult) -> None:
        self.result = result
        self.calls = []

    def resolve(self, request):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        return self.result


class RecordingBinder(TrustedArgumentBinder):
    def __init__(self, *args, events=None, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.calls = []
        self.events = events

    def bind(self, request):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        if self.events is not None:
            self.events.append("binding")
        return super().bind(request)


class RecordingSchemaResolver(ToolSelectionResolver):
    def __init__(self, registry, events):  # type: ignore[no-untyped-def]
        super().__init__(registry)
        self.calls = []
        self.events = events

    def resolve(self, request):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        self.events.append("schema_validation")
        return super().resolve(request)


def write_pipeline(
    result: EntityResolutionResult,
    *,
    state_service: ConversationStateService | None = None,
    state_required_tools=(),
    clock=None,
):
    registry = ToolRegistry()
    for tool_class in WRITE_TOOL_CLASSES:
        registry.register(tool_class)
    policies = build_runtime_binding_policy_registry(registry)
    events = []
    order_resolver = RecordingResolver(result)
    binder = RecordingBinder(
        policies,
        order_resolver,
        known_tool_names=(tool.metadata.name for tool in registry.list()),
        events=events,
    )
    schema_resolver = RecordingSchemaResolver(registry, events)
    pipeline = TrustedSelectionPipeline(
        binder,
        schema_resolver,
        conversation_state_service=state_service,
        state_required_tools=state_required_tools,
        clock=clock,
    )
    return pipeline, binder, schema_resolver, order_resolver, events, registry, policies


def request(tool_name: str, arguments: dict) -> ToolSelectionRequest:
    return ToolSelectionRequest(
        call_id="call-001",
        tool_name=tool_name,
        tool_version="1.0.0",
        arguments=arguments,
    )


def test_binding_occurs_once_before_schema_validation_and_discards_provider_id() -> None:
    pipeline, binder, schema, resolver, events, _, _ = write_pipeline(resolved())
    selection = pipeline.bind_and_validate(
        request(
            "update_delivery_address",
            {"order_number": 123, "delivery_address": " 22 Tahrir Street "},
        ),
        context(),
        "Please update ORD-10025",
    )
    assert events == ["binding", "schema_validation"]
    assert len(binder.calls) == len(schema.calls) == len(resolver.calls) == 1
    assert binder.calls[0].selection.arguments == {
        "order_number": 123,
        "delivery_address": " 22 Tahrir Street ",
    }
    assert schema.calls[0].arguments == {
        "order_number": "ORD-10025",
        "delivery_address": " 22 Tahrir Street ",
    }
    assert selection.arguments == {
        "order_number": "ORD-10025",
        "delivery_address": "22 Tahrir Street",
    }


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (ResolutionStatus.NOT_FOUND, "order_not_found"),
        (ResolutionStatus.FORBIDDEN, "order_forbidden"),
        (ResolutionStatus.STALE, "stale_order_reference"),
    ],
)
def test_resolution_failure_stops_before_schema_validation(status, code) -> None:
    pipeline, binder, schema, resolver, events, _, _ = write_pipeline(
        EntityResolutionResult(
            status=status,
            error_code=code,
            public_message="The order could not be verified.",
        )
    )
    with pytest.raises(TrustedArgumentBindingRejected) as raised:
        pipeline.bind_and_validate(
            request("cancel_order", {"order_number": "PROVIDER-FAKE"}),
            context(),
            "cancel that order",
        )
    assert raised.value.result.failure.code == code
    assert raised.value.result.bound_selection is None
    assert len(binder.calls) == len(resolver.calls) == 1
    assert schema.calls == []
    assert events == ["binding"]


def test_ambiguous_resolution_preserves_structured_clarification() -> None:
    candidates = tuple(
        {
            "entity_type": "order",
            "public_reference": number,
            "relationship": "active",
            "created_at": NOW,
        }
        for number in ("ORD-10025", "ORD-10018")
    )
    pipeline, _, schema, _, _, _, _ = write_pipeline(
        EntityResolutionResult(
            status=ResolutionStatus.CLARIFICATION_REQUIRED,
            candidates=candidates,
            error_code="multiple_orders",
            public_message="Please choose an order.",
        )
    )
    with pytest.raises(TrustedArgumentBindingRejected) as raised:
        pipeline.bind_and_validate(
            request("cancel_order", {"order_number": "provider-choice"}),
            context(),
            "cancel it",
        )
    assert raised.value.result.status.value == "ambiguous_entity"
    assert schema.calls == []


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("cancel_order", {"order_number": "PROVIDER-FAKE"}),
        (
            "update_delivery_address",
            {
                "order_number": "PROVIDER-FAKE",
                "delivery_address": "22 Tahrir Street",
            },
        ),
        ("initiate_refund", {"order_number": "PROVIDER-FAKE"}),
        (
            "create_support_ticket",
            {
                "order_number": "PROVIDER-FAKE",
                "category": "order_issue",
                "issue_description": "The delivered order has a missing item.",
                "escalation_reason": "unresolved_issue",
            },
        ),
    ],
)
def test_all_current_protected_write_tools_receive_verified_order(
    tool_name, arguments
) -> None:
    pipeline, binder, schema, resolver, _, _, _ = write_pipeline(resolved())
    selection = pipeline.bind_and_validate(
        request(tool_name, arguments), context(), "Use order ORD-10025"
    )
    assert selection.arguments["order_number"] == "ORD-10025"
    assert selection.arguments["order_number"] != arguments["order_number"]
    assert len(binder.calls) == len(schema.calls) == len(resolver.calls) == 1


def test_conversation_state_is_loaded_and_passed_to_frozen_binder() -> None:
    state_service = ConversationStateService(InMemoryConversationStateStore())
    state = state_service.create(CONVERSATION_ID)
    pipeline, binder, _, _, _, _, _ = write_pipeline(
        resolved(), state_service=state_service
    )
    pipeline.bind_and_validate(
        request("cancel_order", {"order_number": "PROVIDER-FAKE"}),
        context(),
        "cancel ORD-10025",
    )
    assert binder.calls[0].conversation_state == state


class StateServiceDouble(ConversationStateService):
    def __init__(self, outcome) -> None:  # type: ignore[no-untyped-def]
        super().__init__(InMemoryConversationStateStore())
        self.outcome = outcome

    def load(self, conversation_id):  # type: ignore[no-untyped-def]
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def state_for(
    conversation_id: UUID = CONVERSATION_ID,
    *,
    status: StateStatus = StateStatus.ACTIVE,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> ConversationState:
    service = ConversationStateService(
        InMemoryConversationStateStore(),
        clock=lambda: NOW,
        id_factory=lambda: UUID("00000000-0000-0000-0000-000000000003"),
    )
    state = service.create(conversation_id)
    metadata = state.metadata.model_copy(
        update={"status": status, "expires_at": expires_at}
    )
    return state.model_copy(update={"metadata": metadata}, deep=True)


@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        (None, "conversation_state_required"),
        (
            ConversationStateExpiredError("expired"),
            "conversation_state_expired",
        ),
        (RuntimeError("store unavailable"), "conversation_state_unavailable"),
        (object(), "conversation_state_invalid"),
        (
            state_for(UUID("00000000-0000-0000-0000-000000000099")),
            "conversation_state_forbidden",
        ),
        (
            state_for(status=StateStatus.ARCHIVED),
            "conversation_state_stale",
        ),
        (
            state_for(expires_at=NOW + timedelta(minutes=1)),
            "conversation_state_expired",
        ),
    ],
)
def test_required_state_failures_stop_before_binding(
    outcome, expected_code
) -> None:
    pipeline, binder, schema, resolver, events, _, _ = write_pipeline(
        resolved(),
        state_service=StateServiceDouble(outcome),
        state_required_tools={"cancel_order"},
        clock=lambda: NOW + timedelta(minutes=2),
    )

    with pytest.raises(TrustedArgumentBindingRejected) as raised:
        pipeline.bind_and_validate(
            request("cancel_order", {"order_number": "PROVIDER-FAKE"}),
            context(),
            "cancel it",
        )

    assert raised.value.result.failure.code == expected_code
    assert binder.calls == schema.calls == resolver.calls == []
    assert events == []


def test_required_state_without_state_service_fails_closed() -> None:
    pipeline, binder, schema, resolver, _, _, _ = write_pipeline(
        resolved(), state_required_tools={"cancel_order"}
    )
    with pytest.raises(TrustedArgumentBindingRejected) as raised:
        pipeline.bind_and_validate(
            request("cancel_order", {"order_number": "PROVIDER-FAKE"}),
            context(),
            "cancel it",
        )
    assert raised.value.result.failure.code == "conversation_state_required"
    assert binder.calls == schema.calls == resolver.calls == []


def test_stateless_tool_ignores_unavailable_optional_state() -> None:
    pipeline, binder, schema, resolver, _, _, _ = write_pipeline(
        resolved(),
        state_service=StateServiceDouble(RuntimeError("store unavailable")),
    )
    selection = pipeline.bind_and_validate(
        request("cancel_order", {"order_number": "PROVIDER-FAKE"}),
        context(),
        "cancel ORD-10025",
    )
    assert selection.arguments["order_number"] == "ORD-10025"
    assert len(binder.calls) == len(schema.calls) == len(resolver.calls) == 1


def test_trusted_identity_comes_only_from_execution_context() -> None:
    pipeline, binder, schema, _, _, _, _ = write_pipeline(resolved())
    provider_customer = str(uuid4())
    provider_conversation = str(uuid4())
    selection = pipeline.bind_and_validate(
        request(
            "cancel_order",
            {
                "order_number": "PROVIDER-FAKE",
                "customer_id": provider_customer,
                "conversation_id": provider_conversation,
            },
        ),
        context(),
        "cancel ORD-10025",
    )

    trusted = binder.calls[0].trusted_values
    assert trusted.customer_id == CUSTOMER_ID
    assert trusted.conversation_id == CONVERSATION_ID
    assert provider_customer not in schema.calls[0].model_dump_json()
    assert provider_conversation not in schema.calls[0].model_dump_json()
    assert selection.arguments == {"order_number": "ORD-10025"}


@pytest.mark.parametrize(
    "bad_context",
    [context(customer_id=None), context(conversation_id=None)],
)
def test_missing_trusted_identity_stops_before_binding(bad_context) -> None:
    pipeline, binder, schema, resolver, _, _, _ = write_pipeline(resolved())
    with pytest.raises(InvalidTrustedSelectionRuntimeInputError):
        pipeline.bind_and_validate(
            request("cancel_order", {"order_number": "PROVIDER-FAKE"}),
            bad_context,
            "cancel ORD-10025",
        )
    assert binder.calls == schema.calls == resolver.calls == []


def test_runtime_policies_cover_every_registered_tool_and_validate_at_startup() -> None:
    registry = ToolRegistry()
    registry.register(PingTool)
    for tool_class in WRITE_TOOL_CLASSES:
        registry.register(tool_class)
    policies = build_runtime_binding_policy_registry(registry)
    validate_runtime_binding_configuration(registry, policies)
    assert {policy.tool_name for policy in policies.list_policies()} == {
        tool.metadata.name for tool in registry.list()
    }


def test_bounded_production_loop_has_no_raw_schema_resolver_bypass() -> None:
    parameters = inspect.signature(BoundedModelToolLoopService).parameters
    assert "trusted_selection_pipeline" in parameters
    assert "selection_resolver" not in parameters

    runtime_source = inspect.getsource(BoundedModelToolLoopService._run_bounded)
    assert runtime_source.count("self._selection_pipeline.bind_and_validate(") == 1
    assert runtime_source.count("self._runtime.cycle_service.run(") == 1
    assert runtime_source.index("self._selection_pipeline.bind_and_validate(") < (
        runtime_source.index("self._runtime.cycle_service.run(")
    )
    assert "cycle_service.run(\n                        provider_key,\n                        selection," in runtime_source


def test_complete_execution_order_uses_only_bound_identity_for_auth_audit_and_tool() -> None:
    events: list[str] = []
    registry = ToolRegistry()
    registry.register(CancelOrderTool)
    policies = build_runtime_binding_policy_registry(registry)
    resolver = RecordingResolver(resolved("ORD-10025"))
    binder = RecordingBinder(
        policies,
        resolver,
        known_tool_names=("cancel_order",),
        events=events,
    )
    schema = RecordingSchemaResolver(registry, events)
    pipeline = TrustedSelectionPipeline(binder, schema)

    class RecordingRolePolicy:
        def evaluate(self, role, metadata):  # type: ignore[no-untyped-def]
            events.append("role_authorization")
            return RolePolicyDecision.allow()

    class RecordingToolAuthorization:
        def authorize_tool(self, role, name, version):  # type: ignore[no-untyped-def]
            events.append("tool_authorization")
            return ToolAuthorizationDecision.allow()

    class RecordingOwnershipAuthorization:
        requests = []

        def authorize(self, execution_request, metadata):  # type: ignore[no-untyped-def]
            events.append("ownership_authorization")
            self.requests.append(execution_request)
            return AuthorizationDecision.allow()

    class EventAuditRepository(RecordingAuditRepository):
        def create_running(self, **values):  # type: ignore[no-untyped-def]
            events.append("toolcall_audit")
            return super().create_running(**values)

    class RecordingCancelOrderTool(CancelOrderTool):
        metadata = CancelOrderTool.metadata
        input_schema = CancelOrderTool.input_schema
        output_schema = CancelOrderTool.output_schema
        received_context = None
        received_input = None

        def __init__(self) -> None:
            pass

        def execute(self, execution_context, input_model):  # type: ignore[no-untyped-def]
            events.append("business_execution")
            type(self).received_context = execution_context
            type(self).received_input = input_model
            return ToolResult[WriteToolOutput](
                status=ToolStatus.SUCCESS,
                data=WriteToolOutput(
                    operation="cancel_order",
                    operation_status="cancelled",
                    result_code="cancel_order_completed",
                    message="Order cancelled.",
                    order_reference=input_model.order_number,
                    business_change_applied=True,
                    idempotent_no_op=False,
                ),
            )

    ownership = RecordingOwnershipAuthorization()
    audit = EventAuditRepository()
    adapters = ProviderContinuationAdapterRegistry()
    adapters.register("mock", MockProviderContinuationAdapter())
    runtime = build_tool_continuation_runtime(
        tool_registry=registry,
        continuation_adapter_registry=adapters,
        audit_repository=audit,
        role_policy_service=RecordingRolePolicy(),
        tool_authorization_service=RecordingToolAuthorization(),
        authorization_service=ownership,
        tool_factory=lambda tool_class: RecordingCancelOrderTool(),
    )
    raw_provider_identifier = "PROVIDER-FABRICATED-ORDER"
    trusted_context = context()

    validated = pipeline.bind_and_validate(
        request("cancel_order", {"order_number": raw_provider_identifier}),
        trusted_context,
        "cancel ORD-10025",
    )
    cycle = runtime.cycle_service.run("mock", validated, trusted_context)

    assert events == [
        "binding",
        "schema_validation",
        "role_authorization",
        "tool_authorization",
        "ownership_authorization",
        "toolcall_audit",
        "business_execution",
    ]
    assert len(binder.calls) == len(schema.calls) == len(resolver.calls) == 1
    assert len(ownership.requests) == len(audit.started) == 1
    authorized_request = ownership.requests[0]
    assert authorized_request.arguments == {"order_number": "ORD-10025"}
    assert authorized_request.context.customer_id == CUSTOMER_ID
    assert authorized_request.context.conversation_id == CONVERSATION_ID
    assert audit.started[0]["input_json"] == {"order_number": "ORD-10025"}
    assert raw_provider_identifier not in str(audit.started[0])
    assert RecordingCancelOrderTool.received_input.order_number == "ORD-10025"
    assert RecordingCancelOrderTool.received_context.customer_id == CUSTOMER_ID
    assert cycle.execution_request.arguments == {"order_number": "ORD-10025"}
