"""Seed the commerce tables with deterministic, fully synthetic test data."""

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import func, select

from app.database.models import Customer, Order, OrderItem
from app.database.session import get_session_factory


CUSTOMER_NAMES = (
    ("Mariam", "Test-Amin"),
    ("Omar", "Test-Fahmy"),
    ("Nour", "Test-Salem"),
    ("Youssef", "Test-Hassan"),
    ("Laila", "Test-Maher"),
    ("Karim", "Test-Adel"),
    ("Dina", "Test-Nabil"),
    ("Tarek", "Test-Samir"),
    ("Hana", "Test-Rashad"),
    ("Ziad", "Test-Mansour"),
    ("Salma", "Test-Hafez"),
    ("Ali", "Test-Walid"),
    ("Farah", "Test-Kamal"),
    ("Mostafa", "Test-Rami"),
    ("Aya", "Test-Bassem"),
    ("Hossam", "Test-Nader"),
    ("Rana", "Test-Sayed"),
    ("Amr", "Test-Lotfy"),
    ("Jana", "Test-Maged"),
    ("Adam", "Test-Shawky"),
)

LANGUAGES = ("egyptian_arabic", "arabic", "franco_arabic", "english", "mixed")

ORDER_SCENARIOS = (
    ("pending", "pending"),
    ("confirmed", "paid"),
    ("preparing", "paid"),
    ("dispatched", "paid"),
    ("delayed", "paid"),
    ("delivered", "paid"),
    ("cancelled", "failed"),
    ("cancelled", "refunded"),
    ("delivered", "partially_refunded"),
    ("delayed", "partially_refunded"),
)

PRODUCTS = (
    ("Milk 1L", Decimal("42.50")),
    ("Baladi bread pack", Decimal("18.00")),
    ("Eggs 12-pack", Decimal("78.00")),
    ("Egyptian rice 1kg", Decimal("55.25")),
    ("Pasta 400g", Decimal("29.75")),
    ("Chicken breast 500g", Decimal("145.00")),
    ("Bottled water 6-pack", Decimal("36.00")),
    ("Orange juice 1L", Decimal("48.50")),
    ("Plain yogurt 4-pack", Decimal("39.00")),
    ("White cheese 500g", Decimal("92.00")),
    ("Bananas 1kg", Decimal("38.25")),
    ("Tomatoes 1kg", Decimal("24.50")),
    ("Dish soap", Decimal("47.00")),
    ("Paper towels 2-pack", Decimal("64.00")),
)

ITEM_STATUS_PATTERN = (
    "included",
    "included",
    "included",
    "included",
    "included",
    "included",
    "included",
    "missing",
    "replaced",
    "refunded",
)


def current_counts(session) -> dict[str, int]:
    """Return row counts for the three seed targets."""

    return {
        "customers": session.scalar(select(func.count()).select_from(Customer)),
        "orders": session.scalar(select(func.count()).select_from(Order)),
        "order_items": session.scalar(select(func.count()).select_from(OrderItem)),
    }


def estimated_delivery(status: str, created_at: datetime) -> Optional[datetime]:
    """Return a synthetic delivery estimate appropriate for an order state."""

    if status == "cancelled":
        return None
    if status == "delivered":
        return created_at + timedelta(hours=2)
    if status == "delayed":
        return created_at + timedelta(hours=6)
    return created_at + timedelta(hours=3)


def main() -> int:
    """Seed all commerce records in one transaction."""

    session = get_session_factory()()
    try:
        counts = current_counts(session)
        if any(counts.values()):
            print(f"Seeding skipped: application data already exists ({counts}).")
            return 0

        now = datetime.now(timezone.utc).replace(microsecond=0)
        customers = [
            Customer(
                id=uuid4(),
                first_name=first_name,
                last_name=last_name,
                phone=f"+20-000-000-{index:04d}",
                email=f"cx.customer.{index:02d}@example.com",
                preferred_language=LANGUAGES[(index - 1) % len(LANGUAGES)],
                is_active=index not in {7, 18},
                created_at=now - timedelta(days=90 - index),
                updated_at=now - timedelta(days=10 - (index % 10)),
            )
            for index, (first_name, last_name) in enumerate(CUSTOMER_NAMES, start=1)
        ]
        session.add_all(customers)
        session.flush()

        orders = []
        order_items = []
        item_sequence = 0
        item_counts = (3, 4, 5, 4)

        for order_index in range(1, 51):
            order_id = uuid4()
            status, payment_status = ORDER_SCENARIOS[
                (order_index - 1) % len(ORDER_SCENARIOS)
            ]
            created_at = now - timedelta(days=50 - order_index, hours=order_index % 8)
            total_amount = Decimal("0.00")
            pending_items = []

            for item_offset in range(item_counts[(order_index - 1) % len(item_counts)]):
                product_name, unit_price = PRODUCTS[
                    (order_index * 3 + item_offset) % len(PRODUCTS)
                ]
                quantity = 1 + ((order_index + item_offset) % 3)
                item_status = ITEM_STATUS_PATTERN[
                    item_sequence % len(ITEM_STATUS_PATTERN)
                ]
                item_sequence += 1
                total_amount += unit_price * quantity
                pending_items.append(
                    OrderItem(
                        id=uuid4(),
                        order_id=order_id,
                        product_name=product_name,
                        quantity=quantity,
                        unit_price=unit_price,
                        item_status=item_status,
                        created_at=created_at,
                    )
                )

            orders.append(
                Order(
                    id=order_id,
                    order_number=f"CX-SYN-2026-{order_index:04d}",
                    customer_id=customers[(order_index - 1) % len(customers)].id,
                    status=status,
                    payment_status=payment_status,
                    total_amount=total_amount.quantize(Decimal("0.01")),
                    delivery_address=(
                        f"Synthetic Building {order_index}, Test District, Cairo"
                    ),
                    estimated_delivery_time=estimated_delivery(status, created_at),
                    created_at=created_at,
                    updated_at=created_at + timedelta(minutes=30 + order_index),
                )
            )
            order_items.extend(pending_items)

        session.add_all(orders)
        session.flush()
        session.add_all(order_items)
        session.flush()
        session.commit()

        print(
            "Database seeded successfully: "
            f"{len(customers)} customers, {len(orders)} orders, "
            f"{len(order_items)} order items."
        )
        return 0
    except Exception as error:
        session.rollback()
        print(
            f"Database seeding failed ({type(error).__name__}): {error}",
            file=sys.stderr,
        )
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
