"""add plans modules credits subscriptions

Revision ID: b4e7f8a9c0d1
Revises: a3f1b2c4d5e6
Create Date: 2026-03-14 14:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "b4e7f8a9c0d1"
down_revision: Union[str, None] = "a3f1b2c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- modules
    op.create_table(
        "modules",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False, server_default="feature"),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # -- plans
    op.create_table(
        "plans",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(30), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_monthly", sa.Numeric(10, 2), server_default="0"),
        sa.Column("price_yearly", sa.Numeric(10, 2), server_default="0"),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("ai_credits_monthly", sa.Integer(), server_default="0"),
        sa.Column("max_api_keys", sa.Integer(), server_default="1"),
        sa.Column("max_platforms", sa.Integer(), server_default="1"),
        sa.Column("max_trades_per_day", sa.Integer(), server_default="5"),
        sa.Column("features_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # -- plan_modules (many-to-many with quotas)
    op.create_table(
        "plan_modules",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plan_id", sa.UUID(), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_id", sa.UUID(), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_level", sa.String(20), nullable=False, server_default="full"),
        sa.Column("quota_limit", sa.Integer(), nullable=True),
    )
    op.create_index("ix_plan_modules_plan", "plan_modules", ["plan_id"])
    op.create_index("ix_plan_modules_module", "plan_modules", ["module_id"])
    op.create_unique_constraint("uq_plan_module", "plan_modules", ["plan_id", "module_id"])

    # -- user_subscriptions
    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("plan_id", sa.UUID(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("billing_cycle", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_trial", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # -- credit_balances
    op.create_table(
        "credit_balances",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_earned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lifetime_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # -- credit_transactions
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("tx_type", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), index=True),
    )

    # ------------------------------------------------------------------
    # SEED: default modules
    # ------------------------------------------------------------------
    modules_table = sa.table(
        "modules",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
        sa.column("icon", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(modules_table, [
        {"code": "dashboard",       "name": "Dashboard",          "description": "Overview dashboard with account summary",         "category": "core",     "icon": "LayoutDashboard", "sort_order": 1},
        {"code": "trades",          "name": "Trading",            "description": "Manual and automated trade execution",            "category": "trading",  "icon": "ArrowLeftRight",  "sort_order": 2},
        {"code": "analytics",       "name": "Analytics",          "description": "Performance analytics, equity curve, P&L",        "category": "trading",  "icon": "BarChart3",       "sort_order": 3},
        {"code": "ai_analysis",     "name": "AI Analysis",        "description": "AI-powered market analysis (uses credits)",       "category": "ai",       "icon": "Brain",           "sort_order": 4},
        {"code": "ai_providers",    "name": "AI Providers",       "description": "Configure and switch AI providers",               "category": "ai",       "icon": "Brain",           "sort_order": 5},
        {"code": "bot_control",     "name": "Bot Control",        "description": "Automated trading bot start/stop/settings",       "category": "trading",  "icon": "Bot",             "sort_order": 6},
        {"code": "platforms",       "name": "Platforms",          "description": "Trading platform connections (MT5, Bitkub, etc.)", "category": "trading", "icon": "Server",          "sort_order": 7},
        {"code": "api_keys",        "name": "API Keys",           "description": "Generate and manage API keys",                    "category": "developer","icon": "Key",             "sort_order": 8},
        {"code": "logs",            "name": "Logs",               "description": "System and AI analysis logs",                     "category": "system",   "icon": "ScrollText",      "sort_order": 9},
        {"code": "user_management", "name": "User Management",    "description": "Admin user CRUD, ban, password reset",            "category": "admin",    "icon": "Users",           "sort_order": 10},
        {"code": "mcp",             "name": "MCP Integrations",   "description": "Model Context Protocol server connections",       "category": "advanced", "icon": "Plug",            "sort_order": 11},
        {"code": "export",          "name": "Export",             "description": "Export data to CSV/PDF",                          "category": "feature",  "icon": "Download",        "sort_order": 12},
        {"code": "webhooks",        "name": "Webhooks",           "description": "Outgoing webhook integrations (n8n, Zapier)",     "category": "advanced", "icon": "Webhook",         "sort_order": 13},
        {"code": "settings",        "name": "Settings",           "description": "User profile and preferences",                    "category": "core",     "icon": "Settings",        "sort_order": 14},
    ])

    # ------------------------------------------------------------------
    # SEED: default plans
    # ------------------------------------------------------------------
    plans_table = sa.table(
        "plans",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("price_monthly", sa.Numeric),
        sa.column("price_yearly", sa.Numeric),
        sa.column("ai_credits_monthly", sa.Integer),
        sa.column("max_api_keys", sa.Integer),
        sa.column("max_platforms", sa.Integer),
        sa.column("max_trades_per_day", sa.Integer),
        sa.column("features_json", postgresql.JSONB),
        sa.column("sort_order", sa.Integer),
        sa.column("is_default", sa.Boolean),
    )
    op.bulk_insert(plans_table, [
        {
            "code": "free", "name": "Free", "is_default": True,
            "description": "Get started with basic features and 50 free AI credits",
            "price_monthly": 0, "price_yearly": 0,
            "ai_credits_monthly": 50, "max_api_keys": 1, "max_platforms": 1, "max_trades_per_day": 5,
            "features_json": {"support": "community"},
            "sort_order": 1,
        },
        {
            "code": "starter", "name": "Starter", "is_default": False,
            "description": "For active traders who need more capacity",
            "price_monthly": 19, "price_yearly": 190,
            "ai_credits_monthly": 500, "max_api_keys": 3, "max_platforms": 2, "max_trades_per_day": 30,
            "features_json": {"support": "email"},
            "sort_order": 2,
        },
        {
            "code": "pro", "name": "Pro", "is_default": False,
            "description": "Full access with bot control, advanced analytics, and export",
            "price_monthly": 49, "price_yearly": 490,
            "ai_credits_monthly": 2000, "max_api_keys": 10, "max_platforms": 5, "max_trades_per_day": 100,
            "features_json": {"support": "priority"},
            "sort_order": 3,
        },
        {
            "code": "enterprise", "name": "Enterprise", "is_default": False,
            "description": "Unlimited access with MCP, webhooks, and dedicated support",
            "price_monthly": 149, "price_yearly": 1490,
            "ai_credits_monthly": 99999, "max_api_keys": 100, "max_platforms": 50, "max_trades_per_day": 9999,
            "features_json": {"support": "dedicated", "custom_integrations": True},
            "sort_order": 4,
        },
    ])

    # ------------------------------------------------------------------
    # SEED: plan_modules  (which modules each plan unlocks)
    #   Use raw SQL because we need to reference plan/module IDs by code
    # ------------------------------------------------------------------
    op.execute("""
        INSERT INTO plan_modules (id, plan_id, module_id, access_level, quota_limit)
        SELECT gen_random_uuid(), p.id, m.id,
            CASE
                WHEN p.code = 'free' AND m.code IN ('analytics') THEN 'limited'
                ELSE 'full'
            END,
            CASE
                WHEN m.code = 'api_keys' THEN p.max_api_keys
                WHEN m.code = 'platforms' THEN p.max_platforms
                ELSE NULL
            END
        FROM plans p
        CROSS JOIN modules m
        WHERE
            -- FREE plan modules
            (p.code = 'free' AND m.code IN ('dashboard', 'trades', 'analytics', 'settings'))
            -- STARTER plan modules
            OR (p.code = 'starter' AND m.code IN ('dashboard', 'trades', 'analytics', 'ai_analysis', 'ai_providers', 'platforms', 'api_keys', 'logs', 'settings'))
            -- PRO plan modules
            OR (p.code = 'pro' AND m.code IN ('dashboard', 'trades', 'analytics', 'ai_analysis', 'ai_providers', 'bot_control', 'platforms', 'api_keys', 'logs', 'export', 'settings'))
            -- ENTERPRISE plan modules (everything)
            OR (p.code = 'enterprise')
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_table("credit_transactions")
    op.drop_table("credit_balances")
    op.drop_table("user_subscriptions")
    op.drop_table("plan_modules")
    op.drop_table("plans")
    op.drop_table("modules")
