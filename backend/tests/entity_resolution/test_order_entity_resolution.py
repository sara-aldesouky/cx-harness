from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

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
from app.database.repositories import OrderRepository
from app.entity_resolution import (
    EntityMention,
    EntityResolutionRequest,
    EntityResolutionResult,
    ExistingOrderRepositoryAdapter,
    OrderEntityResolver,
    OrderMentionExtractor,
    OrderResolutionRecord,
    ResolutionCandidate,
    ResolvedEntity,
    ResolutionRequirement,
    ResolutionStatus,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_CUSTOMER_ID = UUID("00000000-0000-0000-0000-000000000002")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000003")


def record(number: str, minutes: int = 0) -> OrderResolutionRecord:
    return OrderResolutionRecord(order_number=number, created_at=NOW + timedelta(minutes=minutes))


class FakeResolutionRepository:
    def __init__(self, *, owned=(), active=(), latest=None, error=False):
        self.owned = {item.order_number: item for item in owned}
        self.active = tuple(active)
        self.latest = latest
        self.error = error
        self.calls = []

    def _check(self):
        if self.error:
            raise RuntimeError("private database failure")

    def find_for_customer(self, customer_id, order_number):
        self._check()
        self.calls.append(("find", customer_id, order_number))
        return self.owned.get(order_number)

    def list_active_for_customer(self, customer_id):
        self._check()
        self.calls.append(("active", customer_id))
        return self.active

    def latest_for_customer(self, customer_id):
        self._check()
        self.calls.append(("latest", customer_id))
        return self.latest


def reference(
    number="ORD-10025",
    relationship=RelationshipType.CURRENT,
    source=VerificationSource.VERIFIED_TOOL_RESULT,
    valid_until=None,
):
    return EntityReference(
        entity_type=EntityType.ORDER,
        relationship=relationship,
        reference=number,
        verification_source=source,
        verified_at=NOW - timedelta(minutes=1),
        valid_until=valid_until,
    )


def conversation_state(*, entities=(), focus=None, status=StateStatus.ACTIVE, expires=None):
    return ConversationState(
        metadata=StateMetadata(
            state_id=uuid4(),
            conversation_id=CONVERSATION_ID,
            revision=4,
            status=status,
            created_at=NOW - timedelta(minutes=10),
            updated_at=NOW - timedelta(minutes=1),
            expires_at=expires or NOW + timedelta(minutes=20),
        ),
        entities=tuple(entities),
        focus=focus or ConversationFocus(),
    )


def request(message, *, state=None, active=True, latest=False):
    return EntityResolutionRequest(
        trusted_customer_id=CUSTOMER_ID,
        conversation_id=CONVERSATION_ID,
        customer_message=message,
        requirement=ResolutionRequirement(
            allow_unique_active_order=active,
            allow_latest_order=latest,
        ),
        conversation_state=state,
    )


def resolver(repository):
    return OrderEntityResolver(repository, clock=lambda: NOW)


def test_explicit_owned_order_resolution_and_case_normalization() -> None:
    repo = FakeResolutionRepository(owned=(record("ORD-10025"),))
    result = resolver(repo).resolve(request("cancel ord-10025 please"))
    assert result.status is ResolutionStatus.RESOLVED
    assert result.resolved_entity.public_reference == "ORD-10025"
    assert result.resolved_entity.verification_source is VerificationSource.REPOSITORY_LOOKUP
    assert result.mentions[0].span_start == 7
    assert repo.calls == [("find", CUSTOMER_ID, "ORD-10025")]
    assert "00000000" not in result.model_dump_json()


@pytest.mark.parametrize("owned", [(), (record("ORD-10018"),)])
def test_explicit_nonexistent_and_cross_customer_are_indistinguishable(owned) -> None:
    result = resolver(FakeResolutionRepository(owned=owned)).resolve(
        request("Show ORD-10025")
    )
    assert result.status is ResolutionStatus.NOT_FOUND
    assert result.error_code == "order_not_found"
    assert result.public_message == "I couldn't find that order for your account."
    assert "customer" not in result.public_message.lower()


def test_multiple_explicit_references_require_clarification_in_order() -> None:
    older = record("ORD-10018", -5)
    newer = record("ORD-10025", 5)
    result = resolver(FakeResolutionRepository(owned=(older, newer))).resolve(
        request("Check ORD-10018 and ORD-10025")
    )
    assert result.status is ResolutionStatus.CLARIFICATION_REQUIRED
    assert [item.public_reference for item in result.candidates] == [
        "ORD-10025",
        "ORD-10018",
    ]
    assert len(result.mentions) == 2


def test_multiple_references_with_insufficient_verified_matches_fail_safely() -> None:
    result = resolver(
        FakeResolutionRepository(owned=(record("ORD-10018"),))
    ).resolve(request("Check ORD-10018 and ORD-99999"))
    assert result.status is ResolutionStatus.INVALID_REFERENCE
    assert result.error_code == "ambiguous_explicit_reference"
    assert not result.candidates


def test_unrelated_numbers_are_ignored_and_unique_active_is_used() -> None:
    repo = FakeResolutionRepository(active=(record("ORD-10025"),))
    result = resolver(repo).resolve(request("I waited 45 minutes and paid 500"))
    assert result.status is ResolutionStatus.RESOLVED
    assert not result.mentions
    assert result.resolved_entity.relationship is RelationshipType.ACTIVE


@pytest.mark.parametrize("malformed", ["ORD-12", "ORD-123456", "ORD-ABCDE"])
def test_malformed_explicit_reference_is_rejected(malformed) -> None:
    result = resolver(FakeResolutionRepository()).resolve(
        request("check " + malformed)
    )
    assert result.status is ResolutionStatus.INVALID_REFERENCE
    assert result.error_code == "invalid_order_reference"


def test_selected_state_order_has_priority_and_is_reverified() -> None:
    selected = reference(relationship=RelationshipType.SELECTED)
    state = conversation_state(entities=(selected,))
    repo = FakeResolutionRepository(owned=(record("ORD-10025"),), active=(record("ORD-10018"),))
    result = resolver(repo).resolve(request("الغيه", state=state))
    assert result.status is ResolutionStatus.RESOLVED
    assert result.resolved_entity.public_reference == "ORD-10025"
    assert result.state_revision == 4
    assert repo.calls[0][0] == "find"


def test_focused_state_order_is_used_after_selected_lookup() -> None:
    focused = reference(relationship=RelationshipType.CURRENT)
    state = conversation_state(
        focus=ConversationFocus(primary_entity=focused, established_at_turn=2)
    )
    result = resolver(
        FakeResolutionRepository(owned=(record("ORD-10025"),))
    ).resolve(request("cancel it", state=state))
    assert result.resolved_entity.relationship is RelationshipType.CURRENT


@pytest.mark.parametrize(
    "untrusted",
    [
        reference(source=VerificationSource.EXPLICIT_CUSTOMER_INPUT),
        reference(valid_until=NOW),
    ],
)
def test_unverified_or_expired_state_reference_is_rejected(untrusted) -> None:
    state = conversation_state(entities=(untrusted.model_copy(update={"relationship": RelationshipType.SELECTED}),))
    result = resolver(FakeResolutionRepository()).resolve(request("الغيه", state=state))
    assert result.status is ResolutionStatus.INVALID_REFERENCE
    assert result.error_code == "unverified_state_reference"


def test_stale_verified_state_reference_does_not_fall_back() -> None:
    state = conversation_state(entities=(reference(relationship=RelationshipType.SELECTED),))
    result = resolver(FakeResolutionRepository(active=(record("ORD-10018"),))).resolve(
        request("cancel it", state=state)
    )
    assert result.status is ResolutionStatus.STALE
    assert result.error_code == "stale_order_reference"


def test_multiple_active_orders_require_clarification_deterministically() -> None:
    repo = FakeResolutionRepository(
        active=(record("ORD-10018", -1), record("ORD-10025", 1))
    )
    result = resolver(repo).resolve(request("فين الأوردر؟"))
    assert result.status is ResolutionStatus.CLARIFICATION_REQUIRED
    assert tuple(item.public_reference for item in result.candidates) == (
        "ORD-10025",
        "ORD-10018",
    )


def test_no_active_orders_does_not_use_latest_unless_permitted() -> None:
    repo = FakeResolutionRepository(latest=record("ORD-10018"))
    blocked = resolver(repo).resolve(request("فين الأوردر؟", latest=False))
    assert blocked.status is ResolutionStatus.NOT_FOUND
    assert not any(call[0] == "latest" for call in repo.calls)
    allowed = resolver(repo).resolve(request("show my latest order", latest=True))
    assert allowed.status is ResolutionStatus.RESOLVED
    assert allowed.resolved_entity.relationship is RelationshipType.LATEST


def test_active_fallback_can_be_disabled() -> None:
    repo = FakeResolutionRepository(active=(record("ORD-10025"),))
    result = resolver(repo).resolve(request("order", active=False))
    assert result.status is ResolutionStatus.NOT_FOUND
    assert repo.calls == []


def test_explicit_correction_overrides_existing_focus_without_mutation() -> None:
    old = reference("ORD-10025")
    state = conversation_state(
        focus=ConversationFocus(primary_entity=old, established_at_turn=1)
    )
    before = state.model_dump_json()
    result = resolver(
        FakeResolutionRepository(owned=(record("ORD-10018"), record("ORD-10025")))
    ).resolve(request("لا، قصدي ORD-10018", state=state))
    assert result.resolved_entity.public_reference == "ORD-10018"
    assert result.resolved_entity.is_customer_correction is True
    assert state.model_dump_json() == before


@pytest.mark.parametrize(
    "status,expires,error",
    [
        (StateStatus.EXPIRED, NOW + timedelta(minutes=1), "conversation_state_expired"),
        (StateStatus.ACTIVE, NOW, "conversation_state_expired"),
        (StateStatus.INVALID, NOW + timedelta(minutes=1), "conversation_state_invalid"),
    ],
)
def test_unusable_conversation_state_fails_safely(status, expires, error) -> None:
    state = conversation_state(status=status, expires=expires)
    result = resolver(FakeResolutionRepository()).resolve(request("order", state=state))
    assert result.error_code == error
    assert result.status in {ResolutionStatus.EXPIRED, ResolutionStatus.INVALID_REFERENCE}


def test_non_order_focus_is_ignored() -> None:
    address = reference().model_copy(update={"entity_type": EntityType.ADDRESS})
    state = conversation_state(
        focus=ConversationFocus(primary_entity=address, established_at_turn=1)
    )
    result = resolver(
        FakeResolutionRepository(active=(record("ORD-10025"),))
    ).resolve(request("order", state=state))
    assert result.resolved_entity.relationship is RelationshipType.ACTIVE


def test_repository_failure_returns_safe_unavailable_result() -> None:
    result = resolver(FakeResolutionRepository(error=True)).resolve(
        request("ORD-10025")
    )
    assert result.status is ResolutionStatus.STALE
    assert result.error_code == "order_resolution_unavailable"
    serialized = result.model_dump_json()
    assert "database" not in serialized
    assert "private" not in serialized


def test_request_requires_matching_partition_and_only_order_requirement() -> None:
    wrong_state = conversation_state().model_copy(
        update={
            "metadata": conversation_state().metadata.model_copy(
                update={"conversation_id": uuid4()}
            )
        }
    )
    with pytest.raises(ValidationError, match="partition"):
        request("order", state=wrong_state)
    with pytest.raises(ValidationError, match="only order"):
        ResolutionRequirement(entity_type=EntityType.REFUND)
    with pytest.raises(ValidationError, match="customer_message"):
        request(" ")


def test_contract_validation_serialization_and_immutability() -> None:
    assert ResolutionRequirement(entity_type=EntityType.ORDER).entity_type is EntityType.ORDER
    mention = EntityMention(
        entity_type=EntityType.ORDER,
        public_reference=" ord-10025 ",
        span_start=0,
        span_end=9,
    )
    candidate = ResolutionCandidate(
        entity_type=EntityType.ORDER,
        public_reference=" ord-10025 ",
        relationship=RelationshipType.ACTIVE,
        created_at=NOW,
    )
    assert mention.public_reference == candidate.public_reference == "ORD-10025"
    with pytest.raises(ValidationError):
        mention.span_start = 2
    assert json.loads(mention.model_dump_json())["entity_type"] == "order"
    with pytest.raises(ValidationError, match="message span"):
        mention.model_copy(update={"span_end": 0}).model_validate(
            {**mention.model_dump(), "span_end": 0}
        )
    with pytest.raises(ValidationError, match="public_reference"):
        EntityMention(entity_type=EntityType.ORDER, public_reference=" ", span_start=0, span_end=1)
    with pytest.raises(ValidationError, match="UTC timezone"):
        ResolutionCandidate(
            entity_type=EntityType.ORDER,
            public_reference="ORD-10025",
            relationship=RelationshipType.ACTIVE,
            created_at=datetime(2026, 1, 1),
        )
    with pytest.raises(ValidationError, match="public_reference"):
        ResolutionCandidate(
            entity_type=EntityType.ORDER,
            public_reference=" ",
            relationship=RelationshipType.ACTIVE,
            created_at=NOW,
        )
    resolved = ResolvedEntity(
        entity_type=EntityType.ORDER,
        public_reference=" ord-10025 ",
        relationship=RelationshipType.CURRENT,
        verification_source=VerificationSource.REPOSITORY_LOOKUP,
        verified_at=NOW,
    )
    assert resolved.public_reference == "ORD-10025"
    with pytest.raises(ValidationError, match="public_reference"):
        ResolvedEntity(
            entity_type=EntityType.ORDER,
            public_reference=" ",
            relationship=RelationshipType.CURRENT,
            verification_source=VerificationSource.REPOSITORY_LOOKUP,
            verified_at=NOW,
        )
    with pytest.raises(ValidationError, match="UTC timezone"):
        resolved.model_validate({**resolved.model_dump(), "verified_at": datetime(2026, 1, 1)})


def test_result_shape_validation() -> None:
    resolved = ResolvedEntity(
        entity_type=EntityType.ORDER,
        public_reference="ORD-10025",
        relationship=RelationshipType.CURRENT,
        verification_source=VerificationSource.REPOSITORY_LOOKUP,
        verified_at=NOW,
    )
    with pytest.raises(ValidationError, match="only resolved_entity"):
        EntityResolutionResult(
            status=ResolutionStatus.RESOLVED,
            resolved_entity=resolved,
            error_code="bad",
            public_message="ok",
        )
    with pytest.raises(ValidationError, match="cannot contain"):
        EntityResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            resolved_entity=resolved,
            public_message="no",
        )
    with pytest.raises(ValidationError, match="at least two"):
        EntityResolutionResult(
            status=ResolutionStatus.CLARIFICATION_REQUIRED,
            candidates=(
                ResolutionCandidate(
                    entity_type=EntityType.ORDER,
                    public_reference="ORD-10025",
                    relationship=RelationshipType.ACTIVE,
                    created_at=NOW,
                ),
            ),
            public_message="choose",
        )
    with pytest.raises(ValidationError, match="error_code"):
        EntityResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            error_code=" ",
            public_message="no",
        )
    with pytest.raises(ValidationError, match="public_message"):
        EntityResolutionResult(status=ResolutionStatus.NOT_FOUND, public_message=" ")
    without_code = EntityResolutionResult(
        status=ResolutionStatus.NOT_FOUND,
        error_code=None,
        public_message="not found",
    )
    assert without_code.error_code is None


def test_mention_extractor_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        OrderMentionExtractor().extract(None)


def test_resolver_validation_and_provider_independence() -> None:
    with pytest.raises(TypeError, match="OrderResolutionRepository"):
        OrderEntityResolver(object())
    valid = resolver(FakeResolutionRepository())
    with pytest.raises(TypeError, match="EntityResolutionRequest"):
        valid.resolve(object())
    invalid_clock = OrderEntityResolver(
        FakeResolutionRepository(), clock=lambda: datetime(2026, 1, 1)
    )
    with pytest.raises(ValueError, match="UTC time"):
        invalid_clock.resolve(request("order"))
    assert "provider" not in EntityResolutionRequest.model_fields
    assert "provider" not in EntityResolutionResult.model_fields


class FakeExistingOrderRepository(OrderRepository):
    def __init__(self, orders, current):
        self.orders = list(orders)
        self.current = list(current)

    def get_by_order_number(self, number):
        return next((item for item in self.orders if item.order_number == number), None)

    def count_current_by_customer_id(self, customer_id):
        return len([item for item in self.current if item.customer_id == customer_id])

    def list_current_by_customer_id(self, customer_id, limit, offset):
        return [item for item in self.current if item.customer_id == customer_id][offset:offset + limit]

    def count_orders(self, *, customer_id=None, **kwargs):
        return len([item for item in self.orders if item.customer_id == customer_id])

    def list_by_customer_id(self, customer_id, limit, offset):
        return [item for item in self.orders if item.customer_id == customer_id][offset:offset + limit]


def order(number, customer=CUSTOMER_ID, minutes=0):
    return SimpleNamespace(
        order_number=number,
        customer_id=customer,
        created_at=NOW + timedelta(minutes=minutes),
    )


def test_existing_repository_adapter_customer_scope_and_ordering() -> None:
    older = order("ORD-10018", minutes=-5)
    same_time_low = order("ORD-10020", minutes=5)
    same_time_high = order("ORD-10025", minutes=5)
    foreign = order("ORD-99999", customer=OTHER_CUSTOMER_ID, minutes=10)
    repository = FakeExistingOrderRepository(
        [older, same_time_low, same_time_high, foreign],
        [older, same_time_low, same_time_high, foreign],
    )
    adapter = ExistingOrderRepositoryAdapter(repository)
    assert adapter.find_for_customer(CUSTOMER_ID, "ORD-10018").order_number == "ORD-10018"
    assert adapter.find_for_customer(CUSTOMER_ID, "ORD-99999") is None
    assert adapter.find_for_customer(CUSTOMER_ID, "ORD-00000") is None
    assert [item.order_number for item in adapter.list_active_for_customer(CUSTOMER_ID)] == [
        "ORD-10025", "ORD-10020", "ORD-10018"
    ]
    assert adapter.latest_for_customer(CUSTOMER_ID).order_number == "ORD-10025"
    assert adapter.list_active_for_customer(uuid4()) == ()
    assert adapter.latest_for_customer(uuid4()) is None
    with pytest.raises(TypeError, match="OrderRepository"):
        ExistingOrderRepositoryAdapter(object())


def test_resolution_record_validation() -> None:
    item = OrderResolutionRecord(
        order_number=" ord-10025 ",
        created_at=NOW.astimezone(timezone(timedelta(hours=2))),
    )
    assert item.order_number == "ORD-10025"
    assert item.created_at.tzinfo == timezone.utc
    with pytest.raises(ValidationError, match="order_number"):
        OrderResolutionRecord(order_number=" ", created_at=NOW)
    with pytest.raises(ValidationError, match="UTC timezone"):
        OrderResolutionRecord(order_number="ORD-10025", created_at=datetime(2026, 1, 1))
