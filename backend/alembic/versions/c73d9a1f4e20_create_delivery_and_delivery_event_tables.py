"""create delivery and delivery event tables

Revision ID: c73d9a1f4e20
Revises: b67119cf8a7c
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c73d9a1f4e20"
down_revision: Optional[str] = "b67119cf8a7c"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "estimated_delivery_time", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('not_started', 'scheduled', 'out_for_delivery', "
            "'delayed', 'delivered', 'failed')",
            name="valid_delivery_status",
        ),
        sa.CheckConstraint(
            "(window_start IS NULL AND window_end IS NULL) OR "
            "(window_start IS NOT NULL AND window_end IS NOT NULL "
            "AND window_end > window_start)",
            name="valid_delivery_window",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_deliveries_order_id"),
    )
    op.create_index("ix_deliveries_order_id", "deliveries", ["order_id"])
    op.create_table(
        "delivery_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("public_description", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('scheduled', 'picked_up', 'out_for_delivery', "
            "'delayed', 'delivery_attempted', 'delivered', 'failed')",
            name="valid_delivery_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"], ["deliveries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_delivery_events_delivery_occurred",
        "delivery_events",
        ["delivery_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delivery_events_delivery_occurred", table_name="delivery_events"
    )
    op.drop_table("delivery_events")
    op.drop_index("ix_deliveries_order_id", table_name="deliveries")
    op.drop_table("deliveries")
