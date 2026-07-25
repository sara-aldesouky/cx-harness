"""add tool call payload truncation flags

Revision ID: b67119cf8a7c
Revises: b601604b54a8
Create Date: 2026-07-25 00:26:45.061137
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b67119cf8a7c"
down_revision: Optional[str] = "b601604b54a8"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    """Apply this migration."""

    op.add_column(
        "tool_calls",
        sa.Column(
            "input_truncated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "tool_calls",
        sa.Column(
            "output_truncated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Revert this migration."""

    op.drop_column("tool_calls", "output_truncated")
    op.drop_column("tool_calls", "input_truncated")
