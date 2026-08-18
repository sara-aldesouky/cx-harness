from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.conversation_state import (
    CURRENT_CONVERSATION_STATE_SCHEMA_VERSION,
    ConversationFocus,
    ConversationState,
    ConversationStateAlreadyExistsError,
    ConversationStateConflictError,
    ConversationStateExpiredError,
    ConversationStateService,
    ConversationStateServiceError,
    ConversationStateStore,
    ConversationStateStoreError,
    EntityReference,
    EntityType,
    InMemoryConversationStateStore,
    LastVerifiedToolOutcome,
    PendingOperation,
    RelationshipType,
    StateMetadata,
    StateStatus,
    VerificationSource,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
STATE_ID = UUID("00000000-0000-0000-0000-000000000001")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000002")


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def entity(**updates: object) -> EntityReference:
    values = {
        "entity_type": EntityType.ORDER,
        "relationship": RelationshipType.CURRENT,
        "reference": " ORD-10025 ",
        "verification_source": VerificationSource.VERIFIED_TOOL_RESULT,
        "verified_at": NOW,
        "valid_until": NOW + timedelta(minutes=10),
        "source_tool_call_id": " call-1 ",
    }
    values.update(updates)
    return EntityReference(**values)


def state(**updates: object) -> ConversationState:
    reference = entity()
    values = {
        "metadata": StateMetadata(
            state_id=STATE_ID,
            conversation_id=CONVERSATION_ID,
            revision=0,
            status=StateStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
        ),
        "focus": ConversationFocus(
            primary_entity=reference,
            related_entities=(reference,),
            established_at_turn=1,
        ),
        "entities": (reference,),
        "pending_operation": PendingOperation(
            operation_name=" update_delivery_address ",
            operation_version=" 1.0.0 ",
            target_entity=reference,
            collected_fields=("order_number",),
            missing_fields=("delivery_address",),
            initiated_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
        "last_verified_tool_outcome": LastVerifiedToolOutcome(
            tool_name=" list_current_orders ",
            tool_version=" 1.0.0 ",
            call_id=" call-1 ",
            succeeded=True,
            outcome_code=" success ",
            verified_at=NOW,
            entity_references=(reference,),
        ),
    }
    values.update(updates)
    return ConversationState(**values)


def test_contracts_are_immutable_normalized_and_provider_independent() -> None:
    snapshot = state()
    assert snapshot.schema_version == CURRENT_CONVERSATION_STATE_SCHEMA_VERSION
    assert snapshot.entities[0].reference == "ORD-10025"
    assert snapshot.entities[0].source_tool_call_id == "call-1"
    assert snapshot.pending_operation.operation_name == "update_delivery_address"
    assert snapshot.last_verified_tool_outcome.outcome_code == "success"
    assert "provider" not in type(snapshot).model_fields
    with pytest.raises(ValidationError):
        snapshot.metadata.revision = 3


def test_serialization_is_stable_json_and_round_trips() -> None:
    snapshot = state()
    first = snapshot.to_json()
    assert first == snapshot.to_json()
    restored = ConversationState.from_json(first)
    assert restored == snapshot
    payload = json.loads(first)
    assert payload["schema_version"] == "1.0"
    assert payload["metadata"]["created_at"].endswith("Z")


def test_unknown_future_schema_version_fails_closed() -> None:
    payload = json.loads(state().to_json())
    payload["schema_version"] = "99.0"
    with pytest.raises(ValidationError, match="schema_version"):
        ConversationState.from_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (lambda: entity(reference=" "), "value must not be empty"),
        (lambda: entity(source_tool_call_id=" "), "value must not be empty"),
        (
            lambda: entity(valid_until=NOW),
            "valid_until must be later than verified_at",
        ),
        (
            lambda: ConversationFocus(established_at_turn=1),
            "focus turn requires a primary entity",
        ),
        (
            lambda: ConversationFocus(primary_entity=entity(), established_at_turn=0),
            "established_at_turn must be positive",
        ),
        (
            lambda: PendingOperation(
                operation_name=" ",
                operation_version="1.0.0",
                initiated_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
            ),
            "value must not be empty",
        ),
        (
            lambda: PendingOperation(
                operation_name="cancel_order",
                operation_version="1.0.0",
                collected_fields=("order_number", "order_number"),
                initiated_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
            ),
            "must not contain duplicates",
        ),
        (
            lambda: PendingOperation(
                operation_name="cancel_order",
                operation_version="1.0.0",
                collected_fields=("order_number",),
                missing_fields=("order_number",),
                initiated_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
            ),
            "both collected and missing",
        ),
        (
            lambda: PendingOperation(
                operation_name="cancel_order",
                operation_version="1.0.0",
                missing_fields=(" ",),
                initiated_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
            ),
            "field names must not be empty",
        ),
        (
            lambda: PendingOperation(
                operation_name="cancel_order",
                operation_version="1.0.0",
                initiated_at=NOW,
                expires_at=NOW,
            ),
            "expires_at must be later",
        ),
        (
            lambda: LastVerifiedToolOutcome(
                tool_name=" ",
                tool_version="1.0.0",
                call_id="call-1",
                succeeded=False,
                verified_at=NOW,
            ),
            "value must not be empty",
        ),
        (
            lambda: StateMetadata(
                state_id=STATE_ID,
                conversation_id=CONVERSATION_ID,
                revision=-1,
                status=StateStatus.ACTIVE,
                created_at=NOW,
                updated_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
            ),
            "revision must be non-negative",
        ),
    ],
)
def test_contract_validation(factory, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        factory()


def test_timestamp_validation_and_normalization() -> None:
    with pytest.raises(ValidationError, match="UTC timezone"):
        entity(verified_at=datetime(2026, 1, 1))
    offset = timezone(timedelta(hours=2))
    reference = entity(verified_at=NOW.astimezone(offset), valid_until=None)
    assert reference.verified_at.tzinfo == timezone.utc


def test_optional_contract_values_remain_none() -> None:
    reference = entity(source_tool_call_id=None, valid_until=None)
    outcome = LastVerifiedToolOutcome(
        tool_name="ping",
        tool_version="1.0.0",
        call_id="call-2",
        succeeded=False,
        outcome_code=None,
        verified_at=NOW,
    )
    assert reference.source_tool_call_id is None
    assert reference.valid_until is None
    assert outcome.outcome_code is None


@pytest.mark.parametrize(
    "updated_at,expires_at,match",
    [
        (NOW - timedelta(seconds=1), NOW + timedelta(minutes=1), "must not precede"),
        (NOW, NOW, "must be later"),
    ],
)
def test_metadata_lifecycle_validation(updated_at, expires_at, match) -> None:
    with pytest.raises(ValidationError, match=match):
        StateMetadata(
            state_id=STATE_ID,
            conversation_id=CONVERSATION_ID,
            revision=0,
            status=StateStatus.ACTIVE,
            created_at=NOW,
            updated_at=updated_at,
            expires_at=expires_at,
        )


def test_store_save_load_and_deep_copy_protection() -> None:
    store = InMemoryConversationStateStore(clock=MutableClock())
    original = state()
    store.save(original)
    loaded = store.load(CONVERSATION_ID)
    assert loaded == original
    assert loaded is not original
    assert loaded.metadata is not original.metadata
    assert store.load(uuid4()) is None


def test_store_rejects_duplicate_and_nonzero_initial_revision() -> None:
    store = InMemoryConversationStateStore(clock=MutableClock())
    store.save(state())
    with pytest.raises(ConversationStateAlreadyExistsError):
        store.save(state())
    other = uuid4()
    nonzero = state(
        metadata=state().metadata.model_copy(
            update={"conversation_id": other, "revision": 1}
        )
    )
    with pytest.raises(ConversationStateConflictError, match="must be zero"):
        store.save(nonzero)


def test_compare_and_swap_success_and_conflict_paths() -> None:
    store = InMemoryConversationStateStore(clock=MutableClock())
    original = state()
    store.save(original)
    revised = original.model_copy(
        update={
            "metadata": original.metadata.model_copy(
                update={"revision": 1, "updated_at": NOW + timedelta(seconds=1)}
            )
        }
    )
    store.compare_and_swap(CONVERSATION_ID, 0, revised)
    assert store.load(CONVERSATION_ID).metadata.revision == 1
    with pytest.raises(ConversationStateConflictError, match="revision conflict"):
        store.compare_and_swap(CONVERSATION_ID, 0, revised)
    with pytest.raises(ConversationStateConflictError, match="increment by one"):
        store.compare_and_swap(CONVERSATION_ID, 1, revised)
    with pytest.raises(ConversationStateConflictError, match="identity mismatch"):
        store.compare_and_swap(uuid4(), 1, revised)
    missing = uuid4()
    missing_state = revised.model_copy(
        update={
            "metadata": revised.metadata.model_copy(
                update={"conversation_id": missing, "revision": 2}
            )
        }
    )
    with pytest.raises(ConversationStateConflictError, match="is missing"):
        store.compare_and_swap(missing, 1, missing_state)


def test_ttl_expiration_is_lazy_and_removes_state() -> None:
    clock = MutableClock()
    store = InMemoryConversationStateStore(clock=clock)
    store.save(state())
    clock.value = NOW + timedelta(minutes=31)
    with pytest.raises(ConversationStateExpiredError):
        store.load(CONVERSATION_ID)
    assert store.load(CONVERSATION_ID) is None


def test_expired_record_can_be_replaced_and_cas_detects_expiration() -> None:
    clock = MutableClock()
    store = InMemoryConversationStateStore(clock=clock)
    original = state()
    store.save(original)
    clock.value = NOW + timedelta(minutes=31)
    store.save(state())
    revised = state().model_copy(
        update={"metadata": state().metadata.model_copy(update={"revision": 1})}
    )
    clock.value = NOW + timedelta(minutes=61)
    with pytest.raises(ConversationStateExpiredError):
        store.compare_and_swap(CONVERSATION_ID, 0, revised)


def test_explicit_expire_and_delete_lifecycle() -> None:
    store = InMemoryConversationStateStore(clock=MutableClock())
    assert store.expire(CONVERSATION_ID) is None
    store.save(state())
    expired = store.expire(CONVERSATION_ID)
    assert expired.metadata.status is StateStatus.EXPIRED
    assert expired.metadata.revision == 1
    with pytest.raises(ConversationStateExpiredError):
        store.load(CONVERSATION_ID)
    assert store.delete(CONVERSATION_ID) is False
    store.save(state())
    assert store.delete(CONVERSATION_ID) is True


def test_invalid_store_clock_fails_safely() -> None:
    store = InMemoryConversationStateStore(clock=lambda: datetime(2026, 1, 1))
    store.save(state())
    with pytest.raises(ConversationStateStoreError, match="UTC time"):
        store.load(CONVERSATION_ID)


def test_service_create_load_save_revision_and_expiration() -> None:
    clock = MutableClock()
    store = InMemoryConversationStateStore(clock=clock)
    service = ConversationStateService(
        store,
        ttl=timedelta(minutes=10),
        clock=clock,
        id_factory=lambda: STATE_ID,
    )
    created = service.create(CONVERSATION_ID)
    assert created.metadata.revision == 0
    assert created.metadata.expires_at == NOW + timedelta(minutes=10)
    assert service.load(CONVERSATION_ID) == created
    clock.value = NOW + timedelta(minutes=2)
    updated = service.save(created)
    assert updated.metadata.revision == 1
    assert updated.metadata.updated_at == clock.value
    assert updated.metadata.expires_at == clock.value + timedelta(minutes=10)
    expired = service.expire(CONVERSATION_ID)
    assert expired.metadata.status is StateStatus.EXPIRED
    assert service.delete(CONVERSATION_ID) is True


def test_service_concurrent_updates_allow_exactly_one_revision() -> None:
    clock = MutableClock()
    service = ConversationStateService(
        InMemoryConversationStateStore(clock=clock), clock=clock
    )
    snapshot = service.create(CONVERSATION_ID)
    barrier = Barrier(2)

    def update() -> str:
        barrier.wait()
        try:
            service.save(snapshot)
        except ConversationStateConflictError:
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: update(), range(2)))
    assert outcomes == ["conflict", "saved"]
    assert service.load(CONVERSATION_ID).metadata.revision == 1


def test_service_configuration_and_clock_validation() -> None:
    store = InMemoryConversationStateStore(clock=MutableClock())
    with pytest.raises(TypeError, match="ConversationStateStore"):
        ConversationStateService(object())
    with pytest.raises(ConversationStateServiceError, match="ttl must be positive"):
        ConversationStateService(store, ttl=timedelta(0))
    with pytest.raises(TypeError, match="id_factory"):
        ConversationStateService(store, id_factory=None)
    service = ConversationStateService(
        store, clock=lambda: datetime(2026, 1, 1)
    )
    with pytest.raises(ConversationStateServiceError, match="UTC time"):
        service.create(CONVERSATION_ID)


def test_store_interface_is_abstract() -> None:
    with pytest.raises(TypeError):
        ConversationStateStore()
