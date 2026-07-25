"""add tool call execution audit fields

Revision ID: b601604b54a8
Revises: d7816236ae9e
Create Date: 2026-07-25 00:10:31.931188
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b601604b54a8"
down_revision: Optional[str] = "d7816236ae9e"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    """Apply this migration."""

    op.add_column(
        "tool_calls",
        sa.Column(
            "execution_id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.add_column(
        "tool_calls", sa.Column("conversation_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "tool_calls", sa.Column("customer_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "tool_calls",
        sa.Column(
            "tool_version",
            sa.String(length=32),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "tool_calls", sa.Column("error_code", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "tool_calls",
        sa.Column("exception_type", sa.String(length=255), nullable=True),
    )
    op.alter_column(
        "tool_calls", "model_run_id", existing_type=sa.UUID(), nullable=True
    )
    op.drop_constraint(
        op.f("ck_tool_calls_valid_status"), "tool_calls", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_tool_calls_valid_status"),
        "tool_calls",
        "status IN ('requested', 'approved', 'executing', 'completed', "
        "'failed', 'rejected', 'running', 'error')",
    )
    op.create_index(
        "ix_tool_calls_conversation_id",
        "tool_calls",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_tool_calls_customer_id",
        "tool_calls",
        ["customer_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_tool_calls_execution_id", "tool_calls", ["execution_id"]
    )
    op.create_foreign_key(
        op.f("fk_tool_calls_conversation_id_conversations"),
        "tool_calls",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_tool_calls_customer_id_customers"),
        "tool_calls",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Revert this migration."""

    op.drop_constraint(
        op.f("fk_tool_calls_customer_id_customers"),
        "tool_calls",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_tool_calls_conversation_id_conversations"),
        "tool_calls",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_tool_calls_execution_id", "tool_calls", type_="unique"
    )
    op.drop_index("ix_tool_calls_customer_id", table_name="tool_calls")
    op.drop_index("ix_tool_calls_conversation_id", table_name="tool_calls")
    op.drop_constraint(
        op.f("ck_tool_calls_valid_status"), "tool_calls", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_tool_calls_valid_status"),
        "tool_calls",
        "status IN ('requested', 'approved', 'executing', 'completed', "
        "'failed', 'rejected')",
    )
    op.alter_column(
        "tool_calls", "model_run_id", existing_type=sa.UUID(), nullable=False
    )
    op.drop_column("tool_calls", "exception_type")
    op.drop_column("tool_calls", "error_code")
    op.drop_column("tool_calls", "tool_version")
    op.drop_column("tool_calls", "customer_id")
    op.drop_column("tool_calls", "conversation_id")
    op.drop_column("tool_calls", "execution_id")
