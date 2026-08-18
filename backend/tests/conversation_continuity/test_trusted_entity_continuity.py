from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from typing import Optional

import pytest
from pydantic import BaseModel, ConfigDict

from app.argument_binding import TrustedArgumentBinder
from app.conversation_continuity import (
    ContinuityFailureCategory,
    ContinuityResolutionMethod,
    TrustedContinuityError,
    TrustedContinuityStore,
    TrustedConversationEntityContinuityService,
    TrustedEntityStatus,
)
from app.entity_resolution import OrderEntityResolver, OrderResolutionRecord
from app.services.trusted_argument_binding_runtime import (
    TrustedSelectionPipeline,
    build_runtime_binding_policy_registry,
)
from app.tools.context import ExecutionContext
from app.tools.execution_request import ToolExecutionRequest
from app.tools.get_order_status import GetOrderStatusTool
from app.tools.registry import ToolRegistry
from app.tools.result import ToolResult, ToolStatus
from app.tools.selection import ToolSelectionRequest, ToolSelectionResolver
from app.tools.write_capabilities import CancelOrderTool


NOW = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
CUSTOMER = UUID("00000000-0000-0000-0000-000000000101")
OTHER_CUSTOMER = UUID("00000000-0000-0000-0000-000000000102")
CONVERSATION = UUID("00000000-0000-0000-0000-000000000201")
OTHER_CONVERSATION = UUID("00000000-0000-0000-0000-000000000202")


class Output(BaseModel):
    model_config = ConfigDict(frozen=True)
    order_number: Optional[str] = None
    orders: tuple[dict[str, str], ...] = ()


def execution_context(*, customer=CUSTOMER, conversation=CONVERSATION):
    return ExecutionContext(
        trace_id=uuid4(), execution_id=uuid4(), customer_id=customer,
        conversation_id=conversation, model_name="qwen3:8b",
    )


def request(tool: str, arguments: dict, *, customer=CUSTOMER, conversation=CONVERSATION):
    return ToolExecutionRequest(
        call_id=str(uuid4()), tool_name=tool, tool_version="1.0.0",
        arguments=arguments,
        context=execution_context(customer=customer, conversation=conversation),
    )


def selection(message_argument="CX-SYN-20********41"):
    return ToolSelectionRequest(
        call_id="provider-call", tool_name="get_order_status", tool_version="1.0.0",
        arguments={"order_id": message_argument},
    )


def service(*, clock=lambda: NOW, max_turn_gap=20):
    return TrustedConversationEntityContinuityService(
        order_tool_names={"get_order_status", "cancel_order"}, clock=clock,
        max_turn_gap=max_turn_gap,
    )


def record_candidates(target):
    target.record_success(
        request("list_current_orders", {"limit": 5, "offset": 0}),
        ToolResult(
            status=ToolStatus.SUCCESS,
            data=Output(orders=(
                {"order_number": "CX-SYN-2026-0041"},
                {"order_number": "CX-SYN-2026-0021"},
            )),
        ),
        1,
    )


def record_selected(target, order="CX-SYN-2026-0041"):
    target.record_success(
        request("get_order_status", {"order_number": order}),
        ToolResult(status=ToolStatus.SUCCESS, data=Output(order_number=order)),
        2,
    )


def test_successful_list_creates_ordered_verified_candidates():
    target = service()
    record_candidates(target)
    state = target.load(CONVERSATION)
    assert state is not None
    assert [item.public_reference for item in state.candidates] == [
        "CX-SYN-2026-0041", "CX-SYN-2026-0021"
    ]
    assert all(item.status is TrustedEntityStatus.VERIFIED for item in state.candidates)
    assert state.selected_entity is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("check the first one", "CX-SYN-2026-0041"),
        ("الأول", "CX-SYN-2026-0041"),
        ("التاني", "CX-SYN-2026-0021"),
        ("awel wa7ed", "CX-SYN-2026-0041"),
        ("el tany", "CX-SYN-2026-0021"),
        ("please check الأول order", "CX-SYN-2026-0041"),
        ("check the last order", "CX-SYN-2026-0021"),
        ("شوف آخر أوردر", "CX-SYN-2026-0021"),
    ],
)
def test_candidate_references_are_resolved_from_trusted_order(message, expected):
    target = service()
    record_candidates(target)
    prepared = target.prepare_binding(
        selection(), execution_context(), message, 3
    )
    assert prepared.resolver_message == expected
    assert prepared.audit.entity_reused is True
    assert prepared.audit.resolution_method is ContinuityResolutionMethod.CANDIDATE_INDEX


@pytest.mark.parametrize(
    "message",
    ["check that order", "الأوردر ده", "el order da", "check it", "ده"],
)
def test_selected_order_references_reuse_verified_state(message):
    target = service()
    record_selected(target)
    prepared = target.prepare_binding(selection(), execution_context(), message, 3)
    assert prepared.resolver_message == "CX-SYN-2026-0041"
    assert prepared.audit.entity_reused is True


def test_masked_identifier_alone_is_never_treated_as_verified():
    target = service()
    record_selected(target)
    with pytest.raises(TrustedContinuityError) as captured:
        target.prepare_binding(
            selection(), execution_context(), "CX-SYN-20********41", 3
        )
    assert captured.value.category is ContinuityFailureCategory.UNSUPPORTED_REFERENCE


def test_ambiguous_reference_without_selected_entity_requests_clarification():
    target = service()
    record_candidates(target)
    with pytest.raises(TrustedContinuityError) as captured:
        target.prepare_binding(selection(), execution_context(), "check that order", 2)
    assert captured.value.category is ContinuityFailureCategory.AMBIGUOUS_REFERENCE


def test_invalid_candidate_index_fails_closed():
    target = service()
    record_candidates(target)
    with pytest.raises(TrustedContinuityError) as captured:
        target.prepare_binding(selection(), execution_context(), "the third one", 2)
    assert captured.value.category is ContinuityFailureCategory.INVALID_CANDIDATE_INDEX


def test_state_cannot_cross_customers_or_conversations():
    target = service()
    record_selected(target)
    with pytest.raises(TrustedContinuityError) as captured:
        target.prepare_binding(selection(), execution_context(customer=OTHER_CUSTOMER), "that order", 3)
    assert captured.value.category is ContinuityFailureCategory.CUSTOMER_MISMATCH
    with pytest.raises(TrustedContinuityError) as missing:
        target.prepare_binding(
            selection(), execution_context(conversation=OTHER_CONVERSATION), "that order", 3
        )
    assert missing.value.category is ContinuityFailureCategory.NO_TRUSTED_ENTITY


def test_stale_state_fails_closed_and_is_removed():
    current = [NOW]
    target = service(clock=lambda: current[0])
    record_selected(target)
    current[0] = NOW + timedelta(hours=1)
    with pytest.raises(TrustedContinuityError) as captured:
        target.prepare_binding(selection(), execution_context(), "that order", 3)
    assert captured.value.category is ContinuityFailureCategory.STALE_ENTITY
    assert target.load(CONVERSATION) is None


def test_turn_expiration_fails_closed():
    target = service(max_turn_gap=1)
    record_selected(target)
    with pytest.raises(TrustedContinuityError) as captured:
        target.prepare_binding(selection(), execution_context(), "that order", 4)
    assert captured.value.category is ContinuityFailureCategory.STALE_ENTITY


def test_failed_tool_result_never_creates_state():
    target = service()
    target.record_success(
        request("get_order_status", {"order_number": "CX-SYN-2026-0041"}),
        ToolResult(status=ToolStatus.FAILURE, error={"error_code": "missing", "public_message": "Missing."}),
        1,
    )
    assert target.load(CONVERSATION) is None


def test_non_order_success_does_not_create_state():
    target = service()
    target.record_success(
        request("get_customer_profile", {"value": "safe"}),
        ToolResult(status=ToolStatus.SUCCESS, data=Output()),
        1,
    )
    assert target.load(CONVERSATION) is None


def test_cleanup_removes_state():
    target = service()
    record_selected(target)
    assert target.clear(CONVERSATION) is True
    assert target.clear(CONVERSATION) is False


def test_store_rejects_non_monotonic_revision():
    target = service()
    record_selected(target)
    state = target.load(CONVERSATION)
    with pytest.raises(TrustedContinuityError) as captured:
        target._store.save(state)  # type: ignore[attr-defined]
    assert captured.value.category is ContinuityFailureCategory.PERSISTENCE_FAILURE


class Repository:
    def __init__(self):
        self.lookups = []
    def find_for_customer(self, customer_id, order_number):
        self.lookups.append((customer_id, order_number))
        if customer_id == CUSTOMER and order_number == "CX-SYN-2026-0041":
            return OrderResolutionRecord(order_number=order_number, created_at=NOW)
        return None
    def list_active_for_customer(self, customer_id):
        return ()
    def latest_for_customer(self, customer_id):
        return None


def test_runtime_reuses_state_but_repository_reverifies_before_binding():
    continuity = service()
    record_selected(continuity)
    registry = ToolRegistry()
    registry.register(CancelOrderTool)
    policies = build_runtime_binding_policy_registry(registry)
    repository = Repository()
    binder = TrustedArgumentBinder(
        policies, OrderEntityResolver(repository), known_tool_names={"cancel_order"}
    )
    pipeline = TrustedSelectionPipeline(
        binder, ToolSelectionResolver(registry), continuity_service=continuity
    )
    validated = pipeline.bind_and_validate(
        ToolSelectionRequest(
            call_id="provider-call", tool_name="cancel_order", tool_version="1.0.0",
            arguments={"order_number": "provider-internal-id"},
        ),
        execution_context(),
        "check that order",
        source_turn=3,
    )
    assert dict(validated.arguments) == {"order_number": "CX-SYN-2026-0041"}
    assert repository.lookups == [(CUSTOMER, "CX-SYN-2026-0041")]


def test_explicit_customer_reference_is_repository_verified_and_provider_value_discarded():
    continuity = service()
    registry = ToolRegistry()
    registry.register(CancelOrderTool)
    policies = build_runtime_binding_policy_registry(registry)
    repository = Repository()
    pipeline = TrustedSelectionPipeline(
        TrustedArgumentBinder(policies, OrderEntityResolver(repository), known_tool_names={"cancel_order"}),
        ToolSelectionResolver(registry),
        continuity_service=continuity,
    )
    validated = pipeline.bind_and_validate(
        ToolSelectionRequest(
            call_id="provider-call", tool_name="cancel_order", tool_version="1.0.0",
            arguments={"order_number": "provider-internal-id"},
        ), execution_context(),
        "check CX-SYN-2026-0041", source_turn=1,
    )
    assert dict(validated.arguments) == {"order_number": "CX-SYN-2026-0041"}
    assert repository.lookups == [(CUSTOMER, "CX-SYN-2026-0041")]


def test_masked_read_argument_is_repaired_from_verified_customer_message():
    continuity = service()
    registry = ToolRegistry()
    registry.register(GetOrderStatusTool)
    policies = build_runtime_binding_policy_registry(registry)
    repository = Repository()
    resolver = OrderEntityResolver(repository)
    pipeline = TrustedSelectionPipeline(
        TrustedArgumentBinder(
            policies, resolver, known_tool_names={"get_order_status"}
        ),
        ToolSelectionResolver(registry),
        continuity_service=continuity,
        continuity_order_resolver=resolver,
        continuity_read_order_tools={"get_order_status"},
    )
    validated = pipeline.bind_and_validate(
        selection("CX-SYN-20********41"), execution_context(),
        "check CX-SYN-2026-0041", source_turn=1,
    )
    assert dict(validated.arguments) == {"order_id": "CX-SYN-2026-0041"}
    assert repository.lookups == [(CUSTOMER, "CX-SYN-2026-0041")]


def test_contracts_are_immutable_and_json_serializable():
    target = service()
    record_selected(target)
    state = target.load(CONVERSATION)
    dumped = state.model_dump_json()
    assert state.model_validate_json(dumped) == state
    with pytest.raises(Exception):
        state.revision = 99
