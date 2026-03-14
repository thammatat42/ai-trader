"""add_ban_fields_and_login_activity

Revision ID: a3f1b2c4d5e6
Revises: 90a256fa371c
Create Date: 2026-03-14 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3f1b2c4d5e6"
down_revision: Union[str, None] = "90a256fa371c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add ban/lock fields to users table
    op.add_column("users", sa.Column("ban_reason", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("banned_by", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))

    # Create login_activity table
    op.create_table(
        "login_activity",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_activity_user_id", "login_activity", ["user_id"])
    op.create_index("ix_login_activity_created_at", "login_activity", ["created_at"])
    op.create_index("ix_login_activity_email", "login_activity", ["email"])
    op.create_index("ix_login_activity_ip_address", "login_activity", ["ip_address"])


def downgrade() -> None:
    op.drop_index("ix_login_activity_ip_address", table_name="login_activity")
    op.drop_index("ix_login_activity_email", table_name="login_activity")
    op.drop_index("ix_login_activity_created_at", table_name="login_activity")
    op.drop_index("ix_login_activity_user_id", table_name="login_activity")
    op.drop_table("login_activity")

    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "banned_by")
    op.drop_column("users", "banned_at")
    op.drop_column("users", "ban_reason")
