"""Refund model relationship and database-constraint tests."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from tests.models.factories import (
    create_customer, create_order, create_payment, create_refund,
    create_refund_eligibility, create_refund_event,
)


def test_refund_relationships(db_session):
    order = create_order(db_session, create_customer(db_session))
    payment = create_payment(db_session, order)
    refund = create_refund(db_session, payment)
    event = create_refund_event(db_session, refund)
    eligibility = create_refund_eligibility(db_session, order)
    assert refund.payment is payment
    assert event.refund is refund
    assert eligibility.order is order


@pytest.mark.parametrize("field,value", [("status", "invalid"), ("amount", Decimal("-0.01")), ("currency", "EG")])
def test_refund_constraints_reject_invalid_values(db_session, field, value):
    payment = create_payment(db_session, create_order(db_session, create_customer(db_session)))
    with pytest.raises(IntegrityError):
        create_refund(db_session, payment, **{field: value})


def test_refund_event_type_constraint(db_session):
    payment = create_payment(db_session, create_order(db_session, create_customer(db_session)))
    refund = create_refund(db_session, payment)
    with pytest.raises(IntegrityError):
        create_refund_event(db_session, refund, event_type="internal")


def test_refund_eligibility_status_constraint(db_session):
    order = create_order(db_session, create_customer(db_session))
    with pytest.raises(IntegrityError):
        create_refund_eligibility(db_session, order, status="approved")
