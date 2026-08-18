from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.argument_binding import (
    ArgumentBindingPolicy,
    ArgumentBindingPolicyNotFoundError,
    ArgumentBindingPolicyRegistry,
    ArgumentBindingRequest,
    ArgumentBindingResult,
    ArgumentProvenance,
    ArgumentSource,
    BindingFailure,
    BindingStatus,
    BoundArgument,
    BoundToolSelectionRequest,
    DuplicateArgumentBindingPolicyError,
    ModelValueBehavior,
    ProviderToolSelection,
    ToolBindingPolicy,
    TrustedArgumentBinder,
    TrustedExecutionValues,
    UnknownArgumentBehavior,
    build_write_argument_binding_policy_registry,
    write_tool_binding_policies,
)
from app.conversation_state import (
    ConversationFocus,
    ConversationState,
    EntityReference,
    EntityType,
    RelationshipType,
    StateMetadata,
    StateStatus,
    VerificationSource,
)
from app.entity_resolution import (
    EntityResolutionResult,
    OrderEntityResolver,
    OrderResolutionRecord,
    ResolutionStatus,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000002")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000003")


class FakeOrderRepository:
    def __init__(self, owned=(), active=(), latest=None, fail=False):
        self.owned = {item.order_number: item for item in owned}
        self.active = tuple(active)
        self.latest = latest
        self.fail = fail
        self.calls = []

    def _raise(self):
        if self.fail:
            raise RuntimeError("private repository failure")

    def find_for_customer(self, customer_id, order_number):
        self._raise()
        self.calls.append(("find", customer_id, order_number))
        return self.owned.get(order_number)

    def list_active_for_customer(self, customer_id):
        self._raise()
        self.calls.append(("active", customer_id))
        return self.active

    def latest_for_customer(self, customer_id):
        self._raise()
        self.calls.append(("latest", customer_id))
        return self.latest


def order(number="ORD-10025", offset=0):
    return OrderResolutionRecord(
        order_number=number, created_at=NOW + timedelta(minutes=offset)
    )


def state_reference(source=VerificationSource.VERIFIED_TOOL_RESULT, number="ORD-10025"):
    return EntityReference(
        entity_type=EntityType.ORDER,
        relationship=RelationshipType.SELECTED,
        reference=number,
        verification_source=source,
        verified_at=NOW - timedelta(minutes=1),
    )


def state(*, reference=None, focus=False, status=StateStatus.ACTIVE, expires=None):
    selected = reference
    return ConversationState(
        metadata=StateMetadata(
            state_id=uuid4(),
            conversation_id=CONVERSATION_ID,
            revision=2,
            status=status,
            created_at=NOW - timedelta(minutes=5),
            updated_at=NOW - timedelta(minutes=1),
            expires_at=expires or NOW + timedelta(minutes=30),
        ),
        entities=(() if selected is None or focus else (selected,)),
        focus=(
            ConversationFocus(primary_entity=selected, established_at_turn=1)
            if selected is not None and focus
            else ConversationFocus()
        ),
    )


def selection(tool="cancel_order", arguments=None):
    return ProviderToolSelection(
        tool_name=tool,
        arguments={} if arguments is None else arguments,
        call_id="call-1",
        safe_source_metadata={"channel": "test"},
    )


def binding_request(tool="cancel_order", arguments=None, message="cancel it", conversation_state=None, **kwargs):
    return ArgumentBindingRequest(
        selection=selection(tool, arguments),
        trusted_values=TrustedExecutionValues(
            customer_id=CUSTOMER_ID, conversation_id=CONVERSATION_ID
        ),
        current_customer_message=message,
        conversation_state=conversation_state,
        **kwargs,
    )


def binder(repository, **kwargs):
    return TrustedArgumentBinder(
        build_write_argument_binding_policy_registry(),
        OrderEntityResolver(repository, clock=lambda: NOW),
        **kwargs,
    )


def argument(result, name):
    return next(
        item for item in result.bound_selection.bound_arguments if item.argument_name == name
    )


@pytest.mark.parametrize("provider_value", ["123456", "ORD-10025"])
def test_provider_order_is_never_trusted_and_is_replaced(provider_value) -> None:
    repo = FakeOrderRepository(active=(order(),))
    result = binder(repo).bind(
        binding_request(arguments={"order_number": provider_value})
    )
    assert result.status is BindingStatus.BOUND
    assert result.bound_selection.arguments == {"order_number": "ORD-10025"}
    bound_order = argument(result, "order_number")
    assert bound_order.provenance.source is ArgumentSource.VERIFIED_ENTITY_RESOLUTION
    assert bound_order.provenance.replaced_model_value is True
    assert bound_order.provenance.injected is False
    assert repo.calls == [("active", CUSTOMER_ID)]
    if provider_value != "ORD-10025":
        assert provider_value not in result.model_dump_json()


def test_missing_provider_order_is_injected_after_resolution() -> None:
    result = binder(FakeOrderRepository(active=(order(),))).bind(binding_request())
    bound_order = argument(result, "order_number")
    assert bound_order.value == "ORD-10025"
    assert bound_order.provenance.injected is True
    assert result.injected_count == 3
    assert result.replaced_count == 0


@pytest.mark.parametrize(
    "message,repo,status",
    [
        ("cancel it", FakeOrderRepository(), BindingStatus.RESOLUTION_FAILED),
        (
            "cancel it",
            FakeOrderRepository(active=(order("ORD-10018"), order("ORD-10025", 1))),
            BindingStatus.AMBIGUOUS_ENTITY,
        ),
        ("cancel ORD-ABCDE", FakeOrderRepository(), BindingStatus.UNTRUSTED_ARGUMENT),
        ("cancel ORD-99999", FakeOrderRepository(), BindingStatus.RESOLUTION_FAILED),
        ("cancel ORD-10025", FakeOrderRepository(fail=True), BindingStatus.RESOLUTION_FAILED),
    ],
)
def test_failed_resolution_never_produces_bound_selection(message, repo, status) -> None:
    result = binder(repo).bind(
        binding_request(arguments={"order_number": "ORD-FAKE"}, message=message)
    )
    assert result.status is status
    assert result.bound_selection is None
    assert result.failure is not None
    assert result.resolution_result.status is not ResolutionStatus.RESOLVED
    assert "ORD-FAKE" not in result.model_dump_json()


@pytest.mark.parametrize(
    "source",
    [VerificationSource.VERIFIED_TOOL_RESULT, VerificationSource.REPOSITORY_LOOKUP],
)
def test_trusted_state_sources_bind_only_after_repository_reverification(source) -> None:
    reference = state_reference(source)
    snapshot = state(reference=reference)
    repo = FakeOrderRepository(owned=(order(),))
    result = binder(repo).bind(binding_request(conversation_state=snapshot))
    assert result.status is BindingStatus.BOUND
    assert repo.calls == [("find", CUSTOMER_ID, "ORD-10025")]
    assert argument(result, "order_number").provenance.source is ArgumentSource.VERIFIED_ENTITY_RESOLUTION


def test_focused_state_reference_reverifies_through_resolver() -> None:
    snapshot = state(reference=state_reference(), focus=True)
    repo = FakeOrderRepository(owned=(order(),))
    result = binder(repo).bind(binding_request(conversation_state=snapshot))
    assert result.bound_selection.arguments["order_number"] == "ORD-10025"
    assert repo.calls[0][0] == "find"


def test_explicit_customer_input_state_cannot_bind_without_reverification() -> None:
    snapshot = state(reference=state_reference(VerificationSource.EXPLICIT_CUSTOMER_INPUT))
    result = binder(FakeOrderRepository(owned=(order(),))).bind(
        binding_request(conversation_state=snapshot)
    )
    assert result.bound_selection is None
    assert result.status is BindingStatus.UNTRUSTED_ARGUMENT


def test_explicit_customer_reference_binds_after_repository_verification() -> None:
    snapshot = state(reference=state_reference(VerificationSource.EXPLICIT_CUSTOMER_INPUT))
    repo = FakeOrderRepository(owned=(order(),))
    result = binder(repo).bind(
        binding_request(message="cancel ORD-10025", conversation_state=snapshot)
    )
    assert result.status is BindingStatus.BOUND
    assert repo.calls == [("find", CUSTOMER_ID, "ORD-10025")]


def test_model_generated_state_reference_cannot_bind() -> None:
    model_reference = EntityReference.model_construct(
        entity_type=EntityType.ORDER,
        relationship=RelationshipType.SELECTED,
        reference="ORD-10025",
        verification_source="model_generated",
        verified_at=NOW,
        valid_until=None,
        source_tool_call_id=None,
    )
    snapshot = state(reference=model_reference)
    result = binder(FakeOrderRepository(owned=(order(),))).bind(
        binding_request(conversation_state=snapshot)
    )
    assert result.bound_selection is None
    assert result.failure.code == "unverified_state_reference"


@pytest.mark.parametrize(
    "snapshot",
    [
        state(reference=state_reference(), status=StateStatus.EXPIRED),
        state(reference=state_reference(), expires=NOW),
    ],
)
def test_expired_state_produces_no_executable_request(snapshot) -> None:
    result = binder(FakeOrderRepository(owned=(order(),))).bind(
        binding_request(conversation_state=snapshot)
    )
    assert result.bound_selection is None
    assert result.failure.resolution_status is ResolutionStatus.EXPIRED


def test_stale_and_cross_customer_state_never_fall_back() -> None:
    snapshot = state(reference=state_reference())
    repo = FakeOrderRepository(active=(order("ORD-10018"),))
    result = binder(repo).bind(
        binding_request(
            arguments={"order_number": "ORD-10018"}, conversation_state=snapshot
        )
    )
    assert result.status is BindingStatus.RESOLUTION_FAILED
    assert repo.calls == [("find", CUSTOMER_ID, "ORD-10025")]
    assert result.bound_selection is None


def test_customer_correction_overrides_state_only_through_resolver() -> None:
    snapshot = state(reference=state_reference())
    repo = FakeOrderRepository(owned=(order("ORD-10018"), order()))
    result = binder(repo).bind(
        binding_request(message="لا، قصدي ORD-10018", conversation_state=snapshot)
    )
    assert result.bound_selection.arguments["order_number"] == "ORD-10018"
    assert result.resolution_result.resolved_entity.is_customer_correction is True


def test_trusted_identity_is_sideband_and_provider_cannot_override() -> None:
    provider_customer = str(OTHER_CUSTOMER_ID)
    provider_conversation = str(uuid4())
    result = binder(FakeOrderRepository(active=(order(),))).bind(
        binding_request(
            arguments={
                "order_number": "bad",
                "customer_id": provider_customer,
                "conversation_id": provider_conversation,
            }
        )
    )
    selection_result = result.bound_selection
    assert "customer_id" not in selection_result.arguments
    assert "conversation_id" not in selection_result.arguments
    assert selection_result.trusted_execution_values.customer_id == CUSTOMER_ID
    assert selection_result.trusted_execution_values.conversation_id == CONVERSATION_ID
    for name in ("customer_id", "conversation_id"):
        item = argument(result, name)
        assert item.value == getattr(selection_result.trusted_execution_values, name)
        assert item.provenance.source is ArgumentSource.EXECUTION_CONTEXT
        assert item.provenance.replaced_model_value is True


def test_unprotected_argument_is_preserved_with_model_provenance() -> None:
    original = {"order_number": "fake", "delivery_address": {"lines": ["22 Tahrir"]}}
    result = binder(FakeOrderRepository(active=(order(),))).bind(
        binding_request(tool="update_delivery_address", arguments=original)
    )
    assert result.bound_selection.arguments["delivery_address"] == {"lines": ("22 Tahrir",)}
    address = argument(result, "delivery_address")
    assert address.provenance.source is ArgumentSource.MODEL_SUGGESTED
    assert address.provenance.protected is False
    original["delivery_address"]["lines"].append("mutated")
    assert result.bound_selection.arguments["delivery_address"] == {"lines": ("22 Tahrir",)}


def test_missing_required_unprotected_value_fails_without_schema_validation() -> None:
    result = binder(FakeOrderRepository(active=(order(),))).bind(
        binding_request(tool="update_delivery_address")
    )
    assert result.status is BindingStatus.MISSING_REQUIRED_ARGUMENT
    assert result.bound_selection is None


def test_all_four_actual_write_policies_are_exact_and_deterministic() -> None:
    policies = write_tool_binding_policies()
    assert [policy.tool_name for policy in policies] == [
        "cancel_order",
        "update_delivery_address",
        "initiate_refund",
        "create_support_ticket",
    ]
    support_names = {item.argument_name for item in policies[-1].argument_policies}
    assert support_names == {
        "order_number", "category", "issue_description", "escalation_reason",
        "customer_id", "conversation_id",
    }
    assert "refund_reason" not in {
        item.argument_name for item in policies[2].argument_policies
    }


def test_support_unprotected_values_are_preserved_without_readiness_decisions() -> None:
    arguments = {
        "category": "missing_item",
        "issue_description": "short",
        "escalation_reason": "customer_requested",
    }
    result = binder(FakeOrderRepository(active=(order(),))).bind(
        binding_request(tool="create_support_ticket", arguments=arguments)
    )
    assert all(result.bound_selection.arguments[key] == value for key, value in arguments.items())
    assert all(argument(result, key).provenance.source is ArgumentSource.MODEL_SUGGESTED for key in arguments)


def test_unknown_tool_and_known_tool_without_policy_fail_closed() -> None:
    instance = binder(FakeOrderRepository(), known_tool_names={"known_read_tool"})
    unknown = instance.bind(binding_request(tool="unknown"))
    unbound = instance.bind(binding_request(tool="known_read_tool"))
    assert unknown.status is BindingStatus.INVALID_TOOL
    assert unbound.status is BindingStatus.POLICY_NOT_FOUND
    assert unknown.bound_selection is unbound.bound_selection is None


def test_unexpected_arguments_reject_or_discard_by_policy() -> None:
    rejected = binder(FakeOrderRepository(active=(order(),))).bind(
        binding_request(arguments={"unexpected": "secret"})
    )
    assert rejected.status is BindingStatus.UNTRUSTED_ARGUMENT

    registry = ArgumentBindingPolicyRegistry()
    registry.register(
        ToolBindingPolicy(
            tool_name="passthrough",
            argument_policies=(
                ArgumentBindingPolicy(
                    argument_name="note",
                    required=False,
                    protected=False,
                    permitted_sources=(ArgumentSource.MODEL_SUGGESTED,),
                    model_value_behavior=ModelValueBehavior.ALLOW,
                ),
            ),
            unknown_argument_behavior=UnknownArgumentBehavior.DISCARD,
        )
    )
    unchanged = TrustedArgumentBinder(
        registry, OrderEntityResolver(FakeOrderRepository(), clock=lambda: NOW)
    ).bind(binding_request(tool="passthrough", arguments={}))
    assert unchanged.status is BindingStatus.UNCHANGED
    assert unchanged.bound_selection.arguments == {}
    discarded = TrustedArgumentBinder(
        registry, OrderEntityResolver(FakeOrderRepository(), clock=lambda: NOW)
    ).bind(binding_request(tool="passthrough", arguments={"extra": "discard"}))
    assert discarded.status is BindingStatus.UNCHANGED


def test_registry_operations_are_thread_safe_copied_and_deterministic() -> None:
    registry = ArgumentBindingPolicyRegistry()
    second, first = write_tool_binding_policies()[:2]
    registry.register(second)
    registry.register(first)
    assert registry.contains(first.tool_name)
    assert [item.tool_name for item in registry.list_policies()] == sorted(
        [first.tool_name, second.tool_name]
    )
    assert registry.get(first.tool_name) == first
    assert registry.get(first.tool_name) is not first
    with pytest.raises(DuplicateArgumentBindingPolicyError):
        registry.register(first)
    with pytest.raises(ArgumentBindingPolicyNotFoundError):
        registry.get("missing")
    with pytest.raises(TypeError):
        registry.register(object())
    with pytest.raises(TypeError):
        registry.contains(None)
    with pytest.raises(ValueError):
        registry.contains(" ")


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"permitted_sources": ()}, "non-empty"),
        ({"permitted_sources": (ArgumentSource.EXECUTION_CONTEXT,) * 2}, "unique"),
        ({"permitted_sources": (ArgumentSource.MODEL_SUGGESTED,)}, "cannot permit"),
        ({"model_value_behavior": ModelValueBehavior.ALLOW}, "must discard"),
    ],
)
def test_invalid_protected_binding_requirements(kwargs, match) -> None:
    values = dict(
        argument_name="order_number",
        required=True,
        protected=True,
        permitted_sources=(ArgumentSource.VERIFIED_ENTITY_RESOLUTION,),
        model_value_behavior=ModelValueBehavior.DISCARD,
        resolution_key="order",
    )
    values.update(kwargs)
    with pytest.raises(ValidationError, match=match):
        ArgumentBindingPolicy(**values)


def test_other_invalid_policy_combinations() -> None:
    optional = ArgumentBindingPolicy(
        argument_name="note", required=False, protected=False,
        permitted_sources=(ArgumentSource.MODEL_SUGGESTED,),
        model_value_behavior=ModelValueBehavior.ALLOW, resolution_key=None,
    )
    assert optional.resolution_key is None
    with pytest.raises(ValidationError, match="value must not be empty"):
        optional.model_validate({**optional.model_dump(), "resolution_key": " "})
    with pytest.raises(ValidationError, match="permit model"):
        ArgumentBindingPolicy(
            argument_name="note", required=False, protected=False,
            permitted_sources=(ArgumentSource.MODEL_SUGGESTED,),
            model_value_behavior=ModelValueBehavior.DISCARD,
        )
    with pytest.raises(ValidationError, match="resolution key"):
        ArgumentBindingPolicy(
            argument_name="note", required=False, protected=False,
            permitted_sources=(ArgumentSource.MODEL_SUGGESTED,),
            model_value_behavior=ModelValueBehavior.ALLOW, resolution_key="order",
        )
    valid = ArgumentBindingPolicy(
        argument_name="order_number", required=True, protected=True,
        permitted_sources=(ArgumentSource.VERIFIED_ENTITY_RESOLUTION,),
        model_value_behavior=ModelValueBehavior.DISCARD, resolution_key="order",
    )
    with pytest.raises(ValidationError, match="non-empty and unique"):
        ToolBindingPolicy(tool_name="tool", argument_policies=(valid, valid), requires_order_resolution=True)
    with pytest.raises(ValidationError, match="resolver configuration"):
        ToolBindingPolicy(tool_name="tool", argument_policies=(valid,))
    with pytest.raises(ValidationError, match="executable"):
        ToolBindingPolicy(tool_name="tool", argument_policies=(valid,), requires_order_resolution=True, executable_when_bound=False)
    with pytest.raises(ValidationError, match="tool_name"):
        ToolBindingPolicy(tool_name=" ", argument_policies=(valid,), requires_order_resolution=True)


def test_contract_validation_immutability_and_serialization() -> None:
    original = {"nested": ["value"]}
    provider = ProviderToolSelection(tool_name=" tool ", arguments=original, call_id=None)
    original["nested"].append("changed")
    assert provider.tool_name == "tool"
    assert provider.arguments == {"nested": ("value",)}
    assert provider.model_dump_json() == provider.model_dump_json()
    with pytest.raises(ValidationError):
        provider.tool_name = "changed"
    with pytest.raises(ValidationError, match="value must not be empty"):
        ProviderToolSelection(tool_name=" ")
    with pytest.raises(ValidationError, match="value must not be empty"):
        ProviderToolSelection(tool_name="tool", call_id=" ")
    provenance = ArgumentProvenance(source=ArgumentSource.SYSTEM_CONFIGURATION, protected=False)
    with pytest.raises(ValidationError, match="argument_name"):
        BoundArgument(argument_name=" ", value="x", provenance=provenance)
    bound = BoundArgument(argument_name="x", value={"items": [1]}, provenance=provenance)
    assert json.loads(bound.model_dump_json())["value"] == {"items": [1]}
    with pytest.raises(ValidationError, match="value must not be empty"):
        BindingFailure(code=" ", public_message="safe")
    trusted = TrustedExecutionValues(
        customer_id=CUSTOMER_ID, conversation_id=CONVERSATION_ID
    )
    selection_contract = BoundToolSelectionRequest(
        tool_name=" tool ", arguments={"x": [1]}, bound_arguments=(bound,),
        trusted_execution_values=trusted, call_id=None,
        safe_source_metadata={"safe": [True]},
    )
    assert selection_contract.tool_name == "tool"
    assert json.loads(selection_contract.model_dump_json())["arguments"] == {"x": [1]}
    with pytest.raises(ValidationError, match="value must not be empty"):
        selection_contract.model_validate({**selection_contract.model_dump(), "call_id": " "})


def test_request_and_result_shape_validation() -> None:
    with_none_correlation = binding_request(correlation_id=None)
    assert with_none_correlation.correlation_id is None
    wrong = state().model_copy(
        update={"metadata": state().metadata.model_copy(update={"conversation_id": uuid4()})}
    )
    with pytest.raises(ValidationError, match="partition"):
        binding_request(conversation_state=wrong)
    with pytest.raises(ValidationError, match="value must not be empty"):
        binding_request(message=" ")
    with pytest.raises(ValidationError, match="successful binding"):
        ArgumentBindingResult(status=BindingStatus.BOUND)
    with pytest.raises(ValidationError, match="failed binding"):
        ArgumentBindingResult(
            status=BindingStatus.INVALID_TOOL,
            bound_selection=BoundToolSelectionRequest(
                tool_name="x", arguments={}, bound_arguments=(),
                trusted_execution_values=TrustedExecutionValues(customer_id=CUSTOMER_ID, conversation_id=CONVERSATION_ID),
            ),
        )
    with pytest.raises(ValidationError, match="non-negative"):
        ArgumentBindingResult(
            status=BindingStatus.INVALID_TOOL,
            failure=BindingFailure(code="bad", public_message="safe"),
            injected_count=-1,
        )


class RecordingResolver:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def resolve(self, request):
        self.requests.append(request)
        return self.result


def test_binder_uses_resolver_result_without_state_or_repository_access() -> None:
    resolved = EntityResolutionResult(
        status=ResolutionStatus.RESOLVED,
        resolved_entity={
            "entity_type": "order", "public_reference": "ORD-10025",
            "relationship": "selected", "verification_source": "repository_lookup",
            "verified_at": NOW,
        },
        public_message="resolved",
    )
    recording = RecordingResolver(resolved)
    instance = TrustedArgumentBinder(build_write_argument_binding_policy_registry(), recording)
    snapshot = state(reference=state_reference(VerificationSource.VERIFIED_TOOL_RESULT))
    before_state = snapshot.model_dump_json()
    before_result = resolved.model_dump_json()
    result = instance.bind(binding_request(conversation_state=snapshot))
    assert result.bound_selection.arguments["order_number"] == "ORD-10025"
    assert len(recording.requests) == 1
    assert snapshot.model_dump_json() == before_state
    assert resolved.model_dump_json() == before_result


def test_binder_constructor_and_request_validation() -> None:
    registry = build_write_argument_binding_policy_registry()
    valid_resolver = RecordingResolver(
        EntityResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            error_code="not_found",
            public_message="safe",
        )
    )
    with pytest.raises(TypeError, match="policy_registry"):
        TrustedArgumentBinder(object(), valid_resolver)
    with pytest.raises(TypeError, match="OrderResolutionService"):
        TrustedArgumentBinder(registry, object())
    instance = TrustedArgumentBinder(registry, valid_resolver)
    with pytest.raises(TypeError, match="ArgumentBindingRequest"):
        instance.bind(object())
    assert "provider" not in ArgumentBindingRequest.model_fields
    assert "repository" not in TrustedArgumentBinder.__dict__
