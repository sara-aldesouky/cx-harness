"""ACID, rollback, concurrency, and audit isolation verification."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.database.models import Customer, Order, Refund, RefundEvent, SupportTicket
from app.tools.context import ExecutionContext
from app.write_operations import (
    CancelOrderInput,
    CancelOrderOperation,
    CreateSupportTicketInput,
    CreateSupportTicketOperation,
    InitiateRefundInput,
    InitiateRefundOperation,
    SQLAlchemyAddressUpdateReader,
    SQLAlchemyAddressUpdateStore,
    SQLAlchemyOrderCancellationReader,
    SQLAlchemyOrderCancellationStore,
    SQLAlchemyRefundInitiationReader,
    SQLAlchemyRefundInitiationStore,
    SQLAlchemySupportTicketReader,
    SQLAlchemySupportTicketStore,
    SQLAlchemyTransactionManager,
    UpdateDeliveryAddressInput,
    UpdateDeliveryAddressOperation,
    WriteExecutionContext,
    WriteFrameworkExecutor,
    WriteSecurityEnvelope,
    WriteStatus,
)
from tests.models.factories import (
    create_customer,
    create_order,
    create_payment,
    create_refund_eligibility,
)


pytestmark = pytest.mark.integration


def context(customer_id):
    return WriteExecutionContext(
        execution_context=ExecutionContext(
            trace_id=uuid4(), execution_id=uuid4(), customer_id=customer_id,
            principal_role="customer",
        ),
        security=WriteSecurityEnvelope(
            authenticated=True, role_policy_allowed=True,
            tool_authorized=True, ownership_authorized=True,
        ),
        request_id=uuid4(), correlation_id=uuid4(),
        requested_at=datetime.now(timezone.utc),
    )


class ExplodingCancellationStore(SQLAlchemyOrderCancellationStore):
    def mark_cancelled(self, order_number, cancelled_at):
        super().mark_cancelled(order_number, cancelled_at)
        raise RuntimeError("injected after mutation")


class ExplodingAddressStore(SQLAlchemyAddressUpdateStore):
    def update_address(self, order_number, delivery_address, updated_at):
        super().update_address(order_number, delivery_address, updated_at)
        raise RuntimeError("injected after mutation")


class ExplodingRefundStore(SQLAlchemyRefundInitiationStore):
    def create_request(self, payment_id, currency, requested_at):
        super().create_request(payment_id, currency, requested_at)
        raise RuntimeError("injected after related objects")


class ExplodingTicketStore(SQLAlchemySupportTicketStore):
    def create_ticket(self, **values):
        super().create_ticket(**values)
        raise RuntimeError("injected after ticket creation")


class FailingAudit:
    def record(self, event):
        raise RuntimeError("audit sink unavailable")


class RecordingAudit:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


class BarrierReader:
    def __init__(self, reader, barrier):
        self.reader = reader
        self.barrier = barrier

    def get(self, *arguments):
        value = self.reader.get(*arguments)
        self.barrier.wait(timeout=10)
        return value


def execute(operation, session_factory, customer_id, input_model, audit=None):
    return WriteFrameworkExecutor(
        SQLAlchemyTransactionManager(session_factory), audit
    ).execute(operation, context(customer_id), input_model)


@pytest.fixture
def hardening_records(test_session_factory):
    suffix = uuid4().hex[:10].upper()
    with test_session_factory() as setup:
        customer = create_customer(
            setup,
            email=f"hardening-{suffix.lower()}@example.test",
            phone=f"+203{suffix.lower()}",
        )
        cancel_order = create_order(
            setup, customer, order_number=f"HARD-CANCEL-{suffix}", status="pending"
        )
        address_order = create_order(
            setup, customer, order_number=f"HARD-ADDRESS-{suffix}",
            status="confirmed", delivery_address="1 Original Street, Cairo",
        )
        refund_order = create_order(
            setup, customer, order_number=f"HARD-REFUND-{suffix}",
            status="delivered", payment_status="paid",
        )
        payment = create_payment(setup, refund_order, status="succeeded", currency="EGP")
        create_refund_eligibility(setup, refund_order, status="eligible")
        ticket_order = create_order(
            setup, customer, order_number=f"HARD-TICKET-{suffix}", status="pending"
        )
        records = {
            "customer_id": customer.id,
            "cancel_id": cancel_order.id,
            "cancel_number": cancel_order.order_number,
            "address_id": address_order.id,
            "address_number": address_order.order_number,
            "address_original": address_order.delivery_address,
            "refund_id": refund_order.id,
            "refund_number": refund_order.order_number,
            "payment_id": payment.id,
            "ticket_id": ticket_order.id,
            "ticket_number": ticket_order.order_number,
        }
        setup.commit()
    try:
        yield records
    finally:
        with test_session_factory.begin() as cleanup:
            cleanup.execute(
                delete(SupportTicket).where(
                    SupportTicket.customer_id == records["customer_id"]
                )
            )
            cleanup.execute(
                delete(Order).where(
                    Order.id.in_(
                        (
                            records["cancel_id"], records["address_id"],
                            records["refund_id"], records["ticket_id"],
                        )
                    )
                )
            )
            cleanup.execute(delete(Customer).where(Customer.id == records["customer_id"]))


def test_all_operations_roll_back_fully_after_post_mutation_failure(
    test_session_factory, hardening_records
) -> None:
    r = hardening_records
    cancellation = execute(
        CancelOrderOperation(
            SQLAlchemyOrderCancellationReader(test_session_factory),
            ExplodingCancellationStore,
        ),
        test_session_factory, r["customer_id"],
        CancelOrderInput(order_number=r["cancel_number"]),
    )
    address = execute(
        UpdateDeliveryAddressOperation(
            SQLAlchemyAddressUpdateReader(test_session_factory), ExplodingAddressStore
        ),
        test_session_factory, r["customer_id"],
        UpdateDeliveryAddressInput(
            order_number=r["address_number"], delivery_address="99 Failed Update Road"
        ),
    )
    refund = execute(
        InitiateRefundOperation(
            SQLAlchemyRefundInitiationReader(test_session_factory), ExplodingRefundStore
        ),
        test_session_factory, r["customer_id"],
        InitiateRefundInput(order_number=r["refund_number"]),
    )
    ticket = execute(
        CreateSupportTicketOperation(
            SQLAlchemySupportTicketReader(test_session_factory), ExplodingTicketStore
        ),
        test_session_factory, r["customer_id"],
        CreateSupportTicketInput(
            category="order_issue",
            issue_description="This injected failure must leave no support ticket behind.",
            escalation_reason="unresolved_issue",
            order_number=r["ticket_number"],
        ),
    )
    assert all(
        result.error.phase.value == "transaction"
        for result in (cancellation, address, refund, ticket)
    )
    with test_session_factory() as verify:
        assert verify.get(Order, r["cancel_id"]).status == "pending"
        assert verify.get(Order, r["address_id"]).delivery_address == r["address_original"]
        assert verify.scalar(
            select(func.count()).select_from(Refund).where(
                Refund.payment_id == r["payment_id"]
            )
        ) == 0
        assert verify.scalar(
            select(func.count()).select_from(RefundEvent)
            .join(RefundEvent.refund).where(Refund.payment_id == r["payment_id"])
        ) == 0
        assert verify.scalar(
            select(func.count()).select_from(SupportTicket).where(
                SupportTicket.customer_id == r["customer_id"]
            )
        ) == 0


def test_audit_failure_cannot_reverse_successful_commit(
    test_session_factory, hardening_records
) -> None:
    r = hardening_records
    result = execute(
        CancelOrderOperation(
            SQLAlchemyOrderCancellationReader(test_session_factory),
            SQLAlchemyOrderCancellationStore,
        ),
        test_session_factory, r["customer_id"],
        CancelOrderInput(order_number=r["cancel_number"]), FailingAudit(),
    )
    assert result.status is WriteStatus.SUCCESS
    with test_session_factory() as verify:
        assert verify.get(Order, r["cancel_id"]).status == "cancelled"


def test_concurrent_same_operation_requests_are_consistent(
    test_session_factory, hardening_records
) -> None:
    r = hardening_records

    def concurrent(operation_factory, input_model):
        barrier = Barrier(2)
        def invoke():
            operation = operation_factory(barrier)
            return execute(
                operation, test_session_factory, r["customer_id"], input_model
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke) for _ in range(2)]
            return [future.result(timeout=15) for future in futures]

    cancellations = concurrent(
        lambda barrier: CancelOrderOperation(
            BarrierReader(SQLAlchemyOrderCancellationReader(test_session_factory), barrier),
            SQLAlchemyOrderCancellationStore,
        ),
        CancelOrderInput(order_number=r["cancel_number"]),
    )
    addresses = concurrent(
        lambda barrier: UpdateDeliveryAddressOperation(
            BarrierReader(SQLAlchemyAddressUpdateReader(test_session_factory), barrier),
            SQLAlchemyAddressUpdateStore,
        ),
        UpdateDeliveryAddressInput(
            order_number=r["address_number"], delivery_address="8 Concurrent Avenue"
        ),
    )
    refunds = concurrent(
        lambda barrier: InitiateRefundOperation(
            BarrierReader(SQLAlchemyRefundInitiationReader(test_session_factory), barrier),
            SQLAlchemyRefundInitiationStore,
        ),
        InitiateRefundInput(order_number=r["refund_number"]),
    )
    tickets = concurrent(
        lambda barrier: CreateSupportTicketOperation(
            BarrierReader(SQLAlchemySupportTicketReader(test_session_factory), barrier),
            SQLAlchemySupportTicketStore,
        ),
        CreateSupportTicketInput(
            category="order_issue",
            issue_description="Two concurrent requests must create only one active ticket.",
            escalation_reason="automation_failed",
            order_number=r["ticket_number"],
        ),
    )

    assert sum(result.status is WriteStatus.SUCCESS for result in cancellations) == 1
    assert all(result.status is WriteStatus.SUCCESS for result in addresses)
    assert sorted(result.outcome.address_updated for result in addresses) == [False, True]
    assert all(result.status is WriteStatus.SUCCESS for result in refunds)
    assert sorted(result.outcome.request_created for result in refunds) == [False, True]
    assert all(result.status is WriteStatus.SUCCESS for result in tickets)
    assert sorted(result.outcome.ticket_created for result in tickets) == [False, True]
    with test_session_factory() as verify:
        assert verify.get(Order, r["cancel_id"]).status == "cancelled"
        assert verify.get(Order, r["address_id"]).delivery_address == "8 Concurrent Avenue"
        assert verify.scalar(
            select(func.count()).select_from(Refund).where(
                Refund.payment_id == r["payment_id"]
            )
        ) == 1
        assert verify.scalar(
            select(func.count()).select_from(RefundEvent)
            .join(RefundEvent.refund).where(Refund.payment_id == r["payment_id"])
        ) == 1
        assert verify.scalar(
            select(func.count()).select_from(SupportTicket).where(
                SupportTicket.customer_id == r["customer_id"]
            )
        ) == 1


def test_mixed_order_operations_do_not_deadlock_or_leave_partial_state(
    test_session_factory, hardening_records
) -> None:
    r = hardening_records
    barrier = Barrier(2)
    cancellation = CancelOrderOperation(
        BarrierReader(SQLAlchemyOrderCancellationReader(test_session_factory), barrier),
        SQLAlchemyOrderCancellationStore,
    )
    address = UpdateDeliveryAddressOperation(
        BarrierReader(SQLAlchemyAddressUpdateReader(test_session_factory), barrier),
        SQLAlchemyAddressUpdateStore,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        cancel_future = pool.submit(
            execute, cancellation, test_session_factory, r["customer_id"],
            CancelOrderInput(order_number=r["cancel_number"]),
        )
        address_future = pool.submit(
            execute, address, test_session_factory, r["customer_id"],
            UpdateDeliveryAddressInput(
                order_number=r["cancel_number"], delivery_address="44 Mixed Operation Road"
            ),
        )
        results = [cancel_future.result(timeout=15), address_future.result(timeout=15)]
    assert any(result.status is WriteStatus.SUCCESS for result in results)
    with test_session_factory() as verify:
        order = verify.get(Order, r["cancel_id"])
        assert order.status == "cancelled"
        assert order.delivery_address in {"Test address", "44 Mixed Operation Road"}


def test_constraint_violation_rolls_back_without_partial_ticket(
    test_session_factory, hardening_records
) -> None:
    r = hardening_records
    fixed_reference = lambda: "TKT-CONSTRAINT01"
    first_operation = CreateSupportTicketOperation(
        SQLAlchemySupportTicketReader(test_session_factory),
        SQLAlchemySupportTicketStore,
        reference_factory=fixed_reference,
    )
    first = execute(
        first_operation, test_session_factory, r["customer_id"],
        CreateSupportTicketInput(
            category="general_inquiry",
            issue_description="The first valid ticket reserves this safe ticket reference.",
            escalation_reason="customer_requested",
        ),
    )
    second_operation = CreateSupportTicketOperation(
        SQLAlchemySupportTicketReader(test_session_factory),
        SQLAlchemySupportTicketStore,
        reference_factory=fixed_reference,
    )
    second = execute(
        second_operation, test_session_factory, r["customer_id"],
        CreateSupportTicketInput(
            category="technical_issue",
            issue_description="A different issue triggers the unique reference constraint.",
            escalation_reason="automation_failed",
        ),
    )
    assert first.status is WriteStatus.SUCCESS
    assert second.error.phase.value == "transaction"
    with test_session_factory() as verify:
        tickets = list(
            verify.scalars(
                select(SupportTicket).where(
                    SupportTicket.customer_id == r["customer_id"]
                )
            )
        )
        assert len(tickets) == 1
        assert tickets[0].ticket_reference == "TKT-CONSTRAINT01"


def test_concurrent_retry_storms_apply_each_business_change_once(
    test_session_factory, hardening_records
) -> None:
    """Exercise realistic duplicate storms against PostgreSQL row locks."""

    r = hardening_records

    def storm(operation_factory, input_model, attempts):
        barrier = Barrier(attempts)
        audit = RecordingAudit()

        def invoke():
            return execute(
                operation_factory(barrier), test_session_factory, r["customer_id"],
                input_model, audit,
            )

        with ThreadPoolExecutor(max_workers=attempts) as pool:
            futures = [pool.submit(invoke) for _ in range(attempts)]
            results = [future.result(timeout=30) for future in futures]
        return results, audit.events

    cancellations, cancellation_audit = storm(
        lambda barrier: CancelOrderOperation(
            BarrierReader(SQLAlchemyOrderCancellationReader(test_session_factory), barrier),
            SQLAlchemyOrderCancellationStore,
        ),
        CancelOrderInput(order_number=r["cancel_number"]),
        5,
    )
    addresses, address_audit = storm(
        lambda barrier: UpdateDeliveryAddressOperation(
            BarrierReader(SQLAlchemyAddressUpdateReader(test_session_factory), barrier),
            SQLAlchemyAddressUpdateStore,
        ),
        UpdateDeliveryAddressInput(
            order_number=r["address_number"],
            delivery_address="18 Retry Safe Boulevard",
        ),
        5,
    )
    refunds, refund_audit = storm(
        lambda barrier: InitiateRefundOperation(
            BarrierReader(SQLAlchemyRefundInitiationReader(test_session_factory), barrier),
            SQLAlchemyRefundInitiationStore,
        ),
        InitiateRefundInput(order_number=r["refund_number"]),
        5,
    )
    tickets, ticket_audit = storm(
        lambda barrier: CreateSupportTicketOperation(
            BarrierReader(SQLAlchemySupportTicketReader(test_session_factory), barrier),
            SQLAlchemySupportTicketStore,
        ),
        CreateSupportTicketInput(
            category="order_issue",
            issue_description="Ten retry attempts must create one support ticket only.",
            escalation_reason="automation_failed",
            order_number=r["ticket_number"],
        ),
        10,
    )

    assert sum(result.status is WriteStatus.SUCCESS for result in cancellations) == 1
    assert sum(
        result.status is WriteStatus.SUCCESS and result.outcome.address_updated
        for result in addresses
    ) == 1
    assert sum(
        result.status is WriteStatus.SUCCESS and result.outcome.request_created
        for result in refunds
    ) == 1
    assert sum(
        result.status is WriteStatus.SUCCESS and result.outcome.ticket_created
        for result in tickets
    ) == 1

    for events, attempts in (
        (cancellation_audit, 5), (address_audit, 5),
        (refund_audit, 5), (ticket_audit, 10),
    ):
        assert len(events) == attempts
        assert sum(event.business_change_applied is True for event in events) == 1

    with test_session_factory() as verify:
        assert verify.get(Order, r["cancel_id"]).status == "cancelled"
        assert (
            verify.get(Order, r["address_id"]).delivery_address
            == "18 Retry Safe Boulevard"
        )
        assert verify.scalar(
            select(func.count()).select_from(Refund).where(
                Refund.payment_id == r["payment_id"]
            )
        ) == 1
        assert verify.scalar(
            select(func.count()).select_from(RefundEvent)
            .join(RefundEvent.refund).where(Refund.payment_id == r["payment_id"])
        ) == 1
        assert verify.scalar(
            select(func.count()).select_from(SupportTicket).where(
                SupportTicket.customer_id == r["customer_id"]
            )
        ) == 1
