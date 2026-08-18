"""Delivery-address update business rules and persistence adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Order
from app.database.repositories import OrderRepository
from app.write_operations.contracts import (
    BaseWriteOperation,
    WriteExecutionContext,
    WriteValidationDecision,
)


ADDRESS_UPDATE_ELIGIBLE_STATUSES = frozenset({"pending", "confirmed", "preparing"})
MAX_DELIVERY_ADDRESS_LENGTH = 500
_ADDRESS_PUNCTUATION = frozenset(" .,'#-/()")


def normalize_delivery_address(value: str) -> str:
    """Normalize whitespace and reject control/symbol characters."""

    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("delivery address must not be empty")
    if len(normalized) > MAX_DELIVERY_ADDRESS_LENGTH:
        raise ValueError(
            f"delivery address must not exceed {MAX_DELIVERY_ADDRESS_LENGTH} characters"
        )
    if not all(character.isalnum() or character in _ADDRESS_PUNCTUATION for character in normalized):
        raise ValueError("delivery address contains unsupported characters")
    if not any(character.isalnum() for character in normalized):
        raise ValueError("delivery address must contain letters or numbers")
    return normalized


class UpdateDeliveryAddressInput(BaseModel):
    """Customer order reference and requested customer-facing address."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    delivery_address: str

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or len(normalized) > 64:
            raise ValueError("order_number must contain 1 to 64 characters")
        return normalized

    @field_validator("delivery_address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        return normalize_delivery_address(value)


class UpdateDeliveryAddressOutput(BaseModel):
    """Customer-safe result; the address itself is intentionally omitted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    status: str
    address_updated: bool
    updated_at: datetime


class AddressUpdateSnapshot(BaseModel):
    """Minimal immutable order state required by the policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_number: str
    customer_id: UUID
    status: str
    delivery_address: str
    updated_at: datetime


class AddressUpdateReader(Protocol):
    def get(self, order_number: str) -> Optional[AddressUpdateSnapshot]: ...


class AddressUpdateStore(Protocol):
    def get_for_update(self, order_number: str) -> Optional[AddressUpdateSnapshot]: ...

    def update_address(
        self, order_number: str, delivery_address: str, updated_at: datetime
    ) -> None: ...


class AddressUpdatePolicy:
    """Central source of ownership, state, and idempotency decisions."""

    @staticmethod
    def evaluate(
        snapshot: Optional[AddressUpdateSnapshot],
        customer_id: UUID,
        requested_address: str,
    ) -> WriteValidationDecision:
        if snapshot is None or snapshot.customer_id != customer_id:
            return WriteValidationDecision.deny(
                "order_not_found", "The requested order was not found."
            )
        if snapshot.status not in ADDRESS_UPDATE_ELIGIBLE_STATUSES:
            return WriteValidationDecision.deny(
                "delivery_address_update_not_allowed",
                "The delivery address can no longer be changed for this order.",
            )
        if normalize_delivery_address(snapshot.delivery_address) == requested_address:
            return WriteValidationDecision.deny(
                "address_already_up_to_date",
                "The delivery address is already up to date.",
            )
        return WriteValidationDecision.allow()


class UpdateDeliveryAddressOperation(
    BaseWriteOperation[UpdateDeliveryAddressInput, UpdateDeliveryAddressOutput, Session]
):
    """Update an eligible owned order without managing its transaction."""

    name = "update_delivery_address"
    version = "1.0.0"
    input_schema = UpdateDeliveryAddressInput
    output_schema = UpdateDeliveryAddressOutput

    def __init__(
        self,
        reader: AddressUpdateReader,
        store_factory: Callable[[Session], AddressUpdateStore],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not callable(getattr(reader, "get", None)):
            raise TypeError("reader must provide get()")
        if not callable(store_factory):
            raise TypeError("store_factory must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._reader = reader
        self._store_factory = store_factory
        self._clock = clock

    def audit_reference(
        self,
        input_model: UpdateDeliveryAddressInput,
        outcome: Optional[UpdateDeliveryAddressOutput] = None,
    ) -> str:
        return input_model.order_number

    def success_message(self, outcome: UpdateDeliveryAddressOutput) -> str:
        return (
            "The delivery address is already up to date."
            if not outcome.address_updated
            else "The delivery address was updated successfully."
        )

    def business_change_applied(self, outcome: UpdateDeliveryAddressOutput) -> bool:
        return outcome.address_updated

    def validate(
        self,
        context: WriteExecutionContext,
        input_model: UpdateDeliveryAddressInput,
    ) -> WriteValidationDecision:
        customer_id = context.execution_context.customer_id
        assert customer_id is not None
        return AddressUpdatePolicy.evaluate(
            self._reader.get(input_model.order_number),
            customer_id,
            input_model.delivery_address,
        )

    def apply(
        self,
        context: WriteExecutionContext,
        input_model: UpdateDeliveryAddressInput,
        transaction: Session,
    ) -> UpdateDeliveryAddressOutput:
        store = self._store_factory(transaction)
        snapshot = store.get_for_update(input_model.order_number)
        customer_id = context.execution_context.customer_id
        assert customer_id is not None
        decision = AddressUpdatePolicy.evaluate(
            snapshot, customer_id, input_model.delivery_address
        )
        if not decision.allowed:
            if decision.failure_code == "address_already_up_to_date" and snapshot:
                return UpdateDeliveryAddressOutput(
                    order_number=input_model.order_number,
                    status=snapshot.status,
                    address_updated=False,
                    updated_at=snapshot.updated_at,
                )
            raise AddressUpdateStateChanged(decision.failure_code or "state_changed")

        updated_at = self._clock()
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError("address update clock must return a timezone-aware value")
        store.update_address(
            input_model.order_number, input_model.delivery_address, updated_at
        )
        return UpdateDeliveryAddressOutput(
            order_number=input_model.order_number,
            status=snapshot.status,
            address_updated=True,
            updated_at=updated_at,
        )


class AddressUpdateStateChanged(RuntimeError):
    """Internal signal that locked state became ineligible after preflight."""


class SQLAlchemyAddressUpdateReader:
    """Read address state through the established OrderRepository."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory

    def get(self, order_number: str) -> Optional[AddressUpdateSnapshot]:
        with self._session_factory() as session:
            return _snapshot(OrderRepository(session).get_by_order_number(order_number))


class SQLAlchemyAddressUpdateStore:
    """Locked ORM adapter used only inside the framework-owned transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._locked_order: Optional[Order] = None

    def get_for_update(self, order_number: str) -> Optional[AddressUpdateSnapshot]:
        self._locked_order = self._session.scalar(
            select(Order).where(Order.order_number == order_number).with_for_update()
        )
        return _snapshot(self._locked_order)

    def update_address(
        self, order_number: str, delivery_address: str, updated_at: datetime
    ) -> None:
        if self._locked_order is None or self._locked_order.order_number != order_number:
            raise RuntimeError("order must be locked before address update")
        self._locked_order.delivery_address = delivery_address
        self._locked_order.updated_at = updated_at


def _snapshot(order: Optional[Order]) -> Optional[AddressUpdateSnapshot]:
    if order is None:
        return None
    return AddressUpdateSnapshot(
        order_number=order.order_number,
        customer_id=order.customer_id,
        status=order.status,
        delivery_address=order.delivery_address,
        updated_at=order.updated_at,
    )
