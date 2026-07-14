"""Verify read-only commerce repositories against the synthetic dataset."""

import sys
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.orm.attributes import NO_VALUE

from app.database.repositories import (
    CustomerRepository,
    OrderItemRepository,
    OrderRepository,
    RepositoryValidationError,
)
from app.database.session import get_session_factory


EXPECTED_COUNTS = {"customers": 20, "orders": 50, "order_items": 199}


def expect_validation_error(operation) -> None:
    """Assert that invalid repository input is rejected consistently."""

    try:
        operation()
    except RepositoryValidationError:
        return
    raise AssertionError("RepositoryValidationError was not raised")


def main() -> int:
    """Run non-destructive repository checks in a read-only transaction."""

    session = get_session_factory()()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        read_only = session.scalar(text("SHOW transaction_read_only"))
        assert read_only == "on"

        inspector = inspect(session.connection())
        tables_before = set(inspector.get_table_names(schema="public"))

        customers = CustomerRepository(session)
        orders = OrderRepository(session)
        items = OrderItemRepository(session)

        counts_before = {
            "customers": customers.count(),
            "orders": orders.count(),
            "order_items": items.count(),
        }
        assert counts_before == EXPECTED_COUNTS

        first_page = customers.list_customers(limit=5)
        second_page = customers.list_customers(limit=5, offset=5)
        repeated_first_page = customers.list_customers(limit=5)
        assert len(first_page) == len(second_page) == 5
        assert [record.id for record in first_page] == [
            record.id for record in repeated_first_page
        ]
        assert {record.id for record in first_page}.isdisjoint(
            record.id for record in second_page
        )

        customer = first_page[0]
        assert customers.get_by_id(customer.id) is customer
        assert customers.get_by_email(customer.email) is customer
        assert customers.get_by_phone(customer.phone) is customer

        customer_orders = customers.list_orders(customer.id, limit=10)
        assert customer_orders
        assert all(order.customer_id == customer.id for order in customer_orders)
        assert [order.id for order in customer_orders] == [
            order.id for order in orders.list_by_customer_id(customer.id, limit=10)
        ]

        customer_with_orders = customers.get_with_orders(customer.id)
        assert customer_with_orders is customer
        assert (
            inspect(customer_with_orders).attrs["orders"].loaded_value is not NO_VALUE
        )
        assert customer_with_orders.orders

        known_order = orders.get_by_order_number("CX-SYN-2026-0001")
        assert known_order is not None
        assert orders.get_by_id(known_order.id) is known_order

        order_with_relations = orders.get_with_customer_and_items(known_order.id)
        assert order_with_relations is known_order
        order_state = inspect(order_with_relations)
        assert order_state.attrs["customer"].loaded_value is not NO_VALUE
        assert order_state.attrs["items"].loaded_value is not NO_VALUE
        assert order_with_relations.customer.id == order_with_relations.customer_id
        assert order_with_relations.items
        assert all(item.order_id == known_order.id for item in order_with_relations.items)

        delayed_orders = orders.list_by_status("delayed", limit=100)
        refunded_orders = orders.list_by_payment_status("refunded", limit=100)
        refunded_items = items.list_by_status("refunded", limit=100)
        known_order_items = items.list_by_order_id(known_order.id, limit=100)
        assert delayed_orders and all(order.status == "delayed" for order in delayed_orders)
        assert refunded_orders and all(
            order.payment_status == "refunded" for order in refunded_orders
        )
        assert refunded_items and all(
            item.item_status == "refunded" for item in refunded_items
        )
        assert known_order_items
        assert items.get_by_id(known_order_items[0].id) is known_order_items[0]

        missing_id = uuid4()
        assert customers.get_by_id(missing_id) is None
        assert orders.get_by_id(missing_id) is None
        assert items.get_by_id(missing_id) is None

        expect_validation_error(lambda: customers.list_customers(limit=0))
        expect_validation_error(lambda: orders.list_orders(offset=-1))
        expect_validation_error(lambda: items.list_items(limit=101))
        expect_validation_error(lambda: orders.list_by_status("unsupported"))
        expect_validation_error(
            lambda: orders.list_by_payment_status("unsupported")
        )
        expect_validation_error(lambda: items.list_by_status("unsupported"))

        counts_after = {
            "customers": customers.count(),
            "orders": orders.count(),
            "order_items": items.count(),
        }
        tables_after = set(inspector.get_table_names(schema="public"))
        assert counts_after == counts_before
        assert tables_after == tables_before

        print(f"Repository verification successful; row counts: {counts_after}")
        print("Transaction mode: read only")
        print(
            "Sample customer: "
            f"{customer.email} ({customer.preferred_language})"
        )
        print(
            "Sample order: "
            f"{known_order.order_number} "
            f"[{known_order.status}/{known_order.payment_status}]"
        )
        print(
            "Sample item: "
            f"{known_order_items[0].product_name} "
            f"[{known_order_items[0].item_status}]"
        )
        print(
            "Filter counts: "
            f"delayed={len(delayed_orders)}, "
            f"refunded_payments={len(refunded_orders)}, "
            f"refunded_items={len(refunded_items)}"
        )
        print("Pagination, eager loading, missing records, and validation passed.")
        return 0
    except Exception as error:
        print(
            f"Repository verification failed ({type(error).__name__}): {error}",
            file=sys.stderr,
        )
        return 1
    finally:
        session.rollback()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
