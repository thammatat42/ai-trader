"""SQLAlchemy ORM models – package init. Import all models here for Alembic discovery."""

from app.models.user import User
from app.models.api_key import ApiKey
from app.models.ai_provider import AiProvider
from app.models.platform import TradingPlatform
from app.models.trade import Trade
from app.models.ai_analysis import AiAnalysisLog
from app.models.bot_settings import BotSettings
from app.models.bot_event import BotEvent
from app.models.audit_log import AuditLog
from app.models.mcp_connection import McpConnection
from app.models.login_activity import LoginActivity

__all__ = [
    "User",
    "ApiKey",
    "AiProvider",
    "TradingPlatform",
    "Trade",
    "AiAnalysisLog",
    "BotSettings",
    "BotEvent",
    "AuditLog",
    "McpConnection",
    "LoginActivity",
]
