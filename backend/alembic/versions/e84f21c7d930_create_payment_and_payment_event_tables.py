"""create payment and payment event tables

Revision ID: e84f21c7d930
Revises: c73d9a1f4e20
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e84f21c7d930"
down_revision: Optional[str] = "c73d9a1f4e20"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("method_type", sa.String(length=32), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("failure_reason_public", sa.Text(), nullable=True),
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
            "status IN ('pending', 'succeeded', 'failed', 'refunded', "
            "'partially_refunded')",
            name="valid_payment_record_status",
        ),
        sa.CheckConstraint(
            "method_type IN ('card', 'cash', 'wallet', 'bank_transfer')",
            name="valid_payment_method_type",
        ),
        sa.CheckConstraint(
            "amount >= 0", name="non_negative_payment_amount"
        ),
        sa.CheckConstraint(
            "char_length(currency) = 3", name="valid_payment_currency"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payments_order_created", "payments", ["order_id", "created_at"]
    )
    op.create_table(
        "payment_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
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
            "event_type IN ('initiated', 'authorized', 'captured', 'failed', "
            "'refund_pending', 'refunded', 'partially_refunded')",
            name="valid_payment_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payment_events_payment_occurred",
        "payment_events",
        ["payment_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_events_payment_occurred", table_name="payment_events"
    )
    op.drop_table("payment_events")
    op.drop_index("ix_payments_order_created", table_name="payments")
    op.drop_table("payments")
