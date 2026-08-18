"""create support ticket table

Revision ID: f4a1c2d3e5b6
Revises: dcc77b6799fd
Create Date: 2026-07-26
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a1c2d3e5b6"
down_revision: Optional[str] = "dcc77b6799fd"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_reference", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("related_order_id", sa.UUID(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("issue_description", sa.Text(), nullable=False),
        sa.Column("issue_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('general_inquiry', 'order_issue', 'delivery_issue', "
            "'payment_issue', 'refund_issue', 'technical_issue')",
            name=op.f("ck_support_tickets_valid_support_ticket_category"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_support_tickets_valid_support_ticket_priority"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name=op.f("ck_support_tickets_valid_support_ticket_status"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"],
            name=op.f("fk_support_tickets_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_order_id"], ["orders.id"],
            name=op.f("fk_support_tickets_related_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_tickets")),
    )
    op.create_index(
        "ix_support_tickets_customer_id", "support_tickets", ["customer_id"]
    )
    op.create_index(
        "ix_support_tickets_related_order_id", "support_tickets", ["related_order_id"]
    )
    op.create_index(
        "ix_support_tickets_ticket_reference",
        "support_tickets",
        ["ticket_reference"],
        unique=True,
    )
    op.create_index(
        "uq_support_tickets_active_issue",
        "support_tickets",
        ["customer_id", "issue_fingerprint"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'in_progress')"),
    )


def downgrade() -> None:
    op.drop_index("uq_support_tickets_active_issue", table_name="support_tickets")
    op.drop_index("ix_support_tickets_ticket_reference", table_name="support_tickets")
    op.drop_index("ix_support_tickets_related_order_id", table_name="support_tickets")
    op.drop_index("ix_support_tickets_customer_id", table_name="support_tickets")
    op.drop_table("support_tickets")
