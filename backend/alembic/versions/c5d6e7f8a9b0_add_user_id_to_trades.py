"""add user_id to trades and indexes

Revision ID: c5d6e7f8a9b0
Revises: b4e7f8a9c0d1
Create Date: 2026-03-14 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4e7f8a9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add user_id FK to trades
    op.add_column(
        "trades",
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("idx_trades_user_id", "trades", ["user_id"])

    # Add composite unique index for (platform_id, order_id) – allows NULLs
    op.create_index(
        "idx_trades_platform_order",
        "trades",
        ["platform_id", "order_id"],
        unique=True,
        postgresql_where=sa.text("order_id IS NOT NULL"),
    )

    # Performance indexes
    op.create_index("idx_trades_platform_status", "trades", ["platform_id", "status"])
    op.create_index("idx_trades_opened", "trades", ["opened_at"])
    op.create_index("idx_trades_closed", "trades", ["closed_at"])
    op.create_index("idx_trades_symbol", "trades", ["symbol"])


def downgrade() -> None:
    op.drop_index("idx_trades_symbol", table_name="trades")
    op.drop_index("idx_trades_closed", table_name="trades")
    op.drop_index("idx_trades_opened", table_name="trades")
    op.drop_index("idx_trades_platform_status", table_name="trades")
    op.drop_index("idx_trades_platform_order", table_name="trades")
    op.drop_index("idx_trades_user_id", table_name="trades")
    op.drop_column("trades", "user_id")
