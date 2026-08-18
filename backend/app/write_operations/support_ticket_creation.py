"""Support-ticket creation policy and transactional persistence adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Optional, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Customer, Order, SupportTicket
from app.database.models.support_ticket import SUPPORT_TICKET_CATEGORIES
from app.database.repositories import OrderRepository
from app.write_operations.contracts import (
    BaseWriteOperation,
    WriteExecutionContext,
    WriteValidationDecision,
)


SUPPORT_ESCALATION_REASONS = (
    "customer_requested",
    "automation_failed",
    "unresolved_issue",
    "operation_blocked",
)
MAX_ISSUE_DESCRIPTION_LENGTH = 2000
MIN_ISSUE_DESCRIPTION_LENGTH = 10


def normalize_issue_description(value: str) -> str:
    """Normalize customer text and reject hidden control characters."""

    normalized = " ".join(value.split())
    if len(normalized) < MIN_ISSUE_DESCRIPTION_LENGTH:
        raise ValueError(
            f"issue description must contain at least {MIN_ISSUE_DESCRIPTION_LENGTH} characters"
        )
    if len(normalized) > MAX_ISSUE_DESCRIPTION_LENGTH:
        raise ValueError(
            f"issue description must not exceed {MAX_ISSUE_DESCRIPTION_LENGTH} characters"
        )
    if any(not character.isprintable() for character in normalized):
        raise ValueError("issue description contains unsupported characters")
    return normalized


class CreateSupportTicketInput(BaseModel):
    """Validated issue data; customer identity remains in trusted context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str
    issue_description: str
    escalation_reason: str
    order_number: Optional[str] = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORT_TICKET_CATEGORIES:
            raise ValueError("unsupported support ticket category")
        return normalized

    @field_validator("escalation_reason")
    @classmethod
    def validate_escalation_reason(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORT_ESCALATION_REASONS:
            raise ValueError("unsupported escalation reason")
        return normalized

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized or len(normalized) > 64:
            raise ValueError("order_number must contain 1 to 64 characters")
        return normalized

    @field_validator("issue_description")
    @classmethod
    def validate_issue_description(cls, value: str) -> str:
        return normalize_issue_description(value)

    @property
    def issue_fingerprint(self) -> str:
        material = "\x1f".join(
            (
                self.category,
                self.order_number or "general",
                self.issue_description.casefold(),
            )
        )
        return sha256(material.encode("utf-8")).hexdigest()


class CreateSupportTicketOutput(BaseModel):
    """Customer-safe acknowledgement without issue text or internal IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_reference: str
    category: str
    priority: str
    status: str
    related_order_number: Optional[str] = None
    ticket_created: bool
    created_at: datetime


class SupportTicketSnapshot(BaseModel):
    """Minimal immutable facts needed to evaluate ticket creation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    customer_exists: bool
    related_order_id: Optional[UUID] = None
    order_owned: bool = True
    existing_ticket_reference: Optional[str] = None
    existing_ticket_priority: Optional[str] = None
    existing_ticket_status: Optional[str] = None
    existing_ticket_created_at: Optional[datetime] = None


class SupportTicketReader(Protocol):
    def get(
        self,
        customer_id: UUID,
        order_number: Optional[str],
        issue_fingerprint: str,
    ) -> SupportTicketSnapshot: ...


class SupportTicketStore(Protocol):
    def get_for_update(
        self,
        customer_id: UUID,
        order_number: Optional[str],
        issue_fingerprint: str,
    ) -> SupportTicketSnapshot: ...

    def create_ticket(
        self,
        *,
        ticket_reference: str,
        customer_id: UUID,
        related_order_id: Optional[UUID],
        category: str,
        priority: str,
        issue_description: str,
        issue_fingerprint: str,
        created_at: datetime,
    ) -> None: ...


class SupportTicketPolicy:
    """Central validation and deterministic priority policy."""

    _HIGH_PRIORITY_CATEGORIES = frozenset({"payment_issue", "refund_issue"})
    _MEDIUM_PRIORITY_CATEGORIES = frozenset(
        {"order_issue", "delivery_issue", "technical_issue"}
    )

    @classmethod
    def evaluate(cls, snapshot: SupportTicketSnapshot) -> WriteValidationDecision:
        if not snapshot.customer_exists:
            return WriteValidationDecision.deny(
                "customer_not_found", "The customer account was not found."
            )
        if not snapshot.order_owned:
            return WriteValidationDecision.deny(
                "order_not_found", "The requested order was not found."
            )
        if snapshot.existing_ticket_reference is not None:
            return WriteValidationDecision.deny(
                "support_ticket_already_exists",
                "An active support ticket already exists for this issue.",
            )
        return WriteValidationDecision.allow()

    @classmethod
    def priority(cls, category: str, escalation_reason: str) -> str:
        if escalation_reason == "operation_blocked":
            return "high"
        if category in cls._HIGH_PRIORITY_CATEGORIES:
            return "high"
        if category in cls._MEDIUM_PRIORITY_CATEGORIES:
            return "medium"
        return "low"


class CreateSupportTicketOperation(
    BaseWriteOperation[CreateSupportTicketInput, CreateSupportTicketOutput, Session]
):
    """Create one support ticket without owning transaction or workflow logic."""

    name = "create_support_ticket"
    version = "1.0.0"
    input_schema = CreateSupportTicketInput
    output_schema = CreateSupportTicketOutput

    def __init__(
        self,
        reader: SupportTicketReader,
        store_factory: Callable[[Session], SupportTicketStore],
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        reference_factory: Callable[[], str] = lambda: f"TKT-{uuid4().hex[:12].upper()}",
    ) -> None:
        if not callable(getattr(reader, "get", None)):
            raise TypeError("reader must provide get()")
        if not callable(store_factory):
            raise TypeError("store_factory must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(reference_factory):
            raise TypeError("reference_factory must be callable")
        self._reader = reader
        self._store_factory = store_factory
        self._clock = clock
        self._reference_factory = reference_factory

    def audit_reference(
        self,
        input_model: CreateSupportTicketInput,
        outcome: Optional[CreateSupportTicketOutput] = None,
    ) -> str:
        references = []
        if outcome is not None:
            references.append(f"ticket:{outcome.ticket_reference}")
        if input_model.order_number is not None:
            references.append(f"order:{input_model.order_number}")
        return "|".join(references) or "support-ticket"

    def success_message(self, outcome: CreateSupportTicketOutput) -> str:
        return (
            "An active support ticket already exists for this issue."
            if not outcome.ticket_created
            else "Your support ticket was created successfully."
        )

    def business_change_applied(self, outcome: CreateSupportTicketOutput) -> bool:
        return outcome.ticket_created

    def validate(
        self, context: WriteExecutionContext, input_model: CreateSupportTicketInput
    ) -> WriteValidationDecision:
        customer_id = context.execution_context.customer_id
        assert customer_id is not None
        return SupportTicketPolicy.evaluate(
            self._reader.get(
                customer_id, input_model.order_number, input_model.issue_fingerprint
            )
        )

    def apply(
        self,
        context: WriteExecutionContext,
        input_model: CreateSupportTicketInput,
        transaction: Session,
    ) -> CreateSupportTicketOutput:
        customer_id = context.execution_context.customer_id
        assert customer_id is not None
        store = self._store_factory(transaction)
        snapshot = store.get_for_update(
            customer_id, input_model.order_number, input_model.issue_fingerprint
        )
        decision = SupportTicketPolicy.evaluate(snapshot)
        if not decision.allowed:
            if (
                decision.failure_code == "support_ticket_already_exists"
                and snapshot.existing_ticket_reference is not None
                and snapshot.existing_ticket_priority is not None
                and snapshot.existing_ticket_status is not None
                and snapshot.existing_ticket_created_at is not None
            ):
                return CreateSupportTicketOutput(
                    ticket_reference=snapshot.existing_ticket_reference,
                    category=input_model.category,
                    priority=snapshot.existing_ticket_priority,
                    status=snapshot.existing_ticket_status,
                    related_order_number=input_model.order_number,
                    ticket_created=False,
                    created_at=snapshot.existing_ticket_created_at,
                )
            raise SupportTicketStateChanged(
                decision.failure_code or "support_ticket_state_changed"
            )

        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("support ticket clock must return a timezone-aware value")
        ticket_reference = self._reference_factory().strip().upper()
        if not ticket_reference.startswith("TKT-") or len(ticket_reference) > 32:
            raise ValueError("ticket reference factory returned an invalid reference")
        priority = SupportTicketPolicy.priority(
            input_model.category, input_model.escalation_reason
        )
        store.create_ticket(
            ticket_reference=ticket_reference,
            customer_id=customer_id,
            related_order_id=snapshot.related_order_id,
            category=input_model.category,
            priority=priority,
            issue_description=input_model.issue_description,
            issue_fingerprint=input_model.issue_fingerprint,
            created_at=created_at,
        )
        return CreateSupportTicketOutput(
            ticket_reference=ticket_reference,
            category=input_model.category,
            priority=priority,
            status="open",
            related_order_number=input_model.order_number,
            ticket_created=True,
            created_at=created_at,
        )


class SupportTicketStateChanged(RuntimeError):
    """Internal signal that locked state changed after preflight."""


class SQLAlchemySupportTicketReader:
    """Read customer, ownership, and active duplicate state."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory

    def get(
        self,
        customer_id: UUID,
        order_number: Optional[str],
        issue_fingerprint: str,
    ) -> SupportTicketSnapshot:
        with self._session_factory() as session:
            return _snapshot(session, customer_id, order_number, issue_fingerprint)


class SQLAlchemySupportTicketStore:
    """Serialize creation by locking the trusted customer and related order."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._locked_customer = False

    def get_for_update(
        self,
        customer_id: UUID,
        order_number: Optional[str],
        issue_fingerprint: str,
    ) -> SupportTicketSnapshot:
        self._locked_customer = self._session.scalar(
            select(Customer.id).where(Customer.id == customer_id).with_for_update()
        ) is not None
        related_order_id = None
        order_owned = True
        if self._locked_customer and order_number is not None:
            locked_order = self._session.scalar(
                select(Order).where(Order.order_number == order_number).with_for_update()
            )
            related_order_id = locked_order.id if locked_order is not None else None
            order_owned = (
                locked_order is not None and locked_order.customer_id == customer_id
            )
        existing = (
            _existing_ticket(self._session, customer_id, issue_fingerprint)
            if self._locked_customer
            else None
        )
        return SupportTicketSnapshot(
            customer_exists=self._locked_customer,
            related_order_id=related_order_id,
            order_owned=order_owned,
            existing_ticket_reference=(
                existing.ticket_reference if existing else None
            ),
            existing_ticket_priority=(existing.priority if existing else None),
            existing_ticket_status=(existing.status if existing else None),
            existing_ticket_created_at=(existing.created_at if existing else None),
        )

    def create_ticket(
        self,
        *,
        ticket_reference: str,
        customer_id: UUID,
        related_order_id: Optional[UUID],
        category: str,
        priority: str,
        issue_description: str,
        issue_fingerprint: str,
        created_at: datetime,
    ) -> None:
        if not self._locked_customer:
            raise RuntimeError("customer must be locked before ticket creation")
        self._session.add(
            SupportTicket(
                ticket_reference=ticket_reference,
                customer_id=customer_id,
                related_order_id=related_order_id,
                category=category,
                priority=priority,
                status="open",
                issue_description=issue_description,
                issue_fingerprint=issue_fingerprint,
                created_at=created_at,
                updated_at=created_at,
            )
        )


def _snapshot(
    session: Session,
    customer_id: UUID,
    order_number: Optional[str],
    issue_fingerprint: str,
) -> SupportTicketSnapshot:
    customer_exists = session.scalar(
        select(Customer.id).where(Customer.id == customer_id)
    ) is not None
    related_order_id = None
    order_owned = True
    if order_number is not None and customer_exists:
        order = OrderRepository(session).get_by_order_number(order_number)
        related_order_id = order.id if order is not None else None
        order_owned = order is not None and order.customer_id == customer_id
    existing = (
        _existing_ticket(session, customer_id, issue_fingerprint)
        if customer_exists
        else None
    )
    return SupportTicketSnapshot(
        customer_exists=customer_exists,
        related_order_id=related_order_id,
        order_owned=order_owned,
        existing_ticket_reference=(existing.ticket_reference if existing else None),
        existing_ticket_priority=(existing.priority if existing else None),
        existing_ticket_status=(existing.status if existing else None),
        existing_ticket_created_at=(existing.created_at if existing else None),
    )


def _existing_ticket(
    session: Session, customer_id: UUID, issue_fingerprint: str
) -> Optional[SupportTicket]:
    return session.scalar(
        select(SupportTicket)
        .where(
            SupportTicket.customer_id == customer_id,
            SupportTicket.issue_fingerprint == issue_fingerprint,
            SupportTicket.status.in_(("open", "in_progress")),
        )
        .order_by(SupportTicket.created_at.asc(), SupportTicket.id.asc())
        .limit(1)
    )
