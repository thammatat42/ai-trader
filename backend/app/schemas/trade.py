"""Pydantic schemas for trades, platforms, and related API operations."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
#  Price
# ---------------------------------------------------------------------------
class PriceResponse(BaseModel):
    symbol: str
    bid: float
    ask: float
    timestamp: int


# ---------------------------------------------------------------------------
#  Trade
# ---------------------------------------------------------------------------
class TradeResponse(BaseModel):
    id: UUID
    platform_id: UUID | None = None
    order_id: str | None = None
    symbol: str
    action: str
    lot: float
    open_price: float | None = None
    close_price: float | None = None
    sl_price: float | None = None
    tp_price: float | None = None
    profit: float | None = None
    commission: float | None = None
    swap: float | None = None
    status: str
    ai_provider_id: UUID | None = None
    ai_analysis_id: UUID | None = None
    opened_at: datetime
    closed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ManualTradeRequest(BaseModel):
    platform_id: UUID
    symbol: str = Field(default="XAUUSD", max_length=30)
    action: str = Field(..., pattern="^(BUY|SELL)$")
    lot: float = Field(gt=0, le=100)
    sl_price: float
    tp_price: float


class TradeListParams(BaseModel):
    status: str | None = None
    platform_id: UUID | None = None
    symbol: str | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)


# ---------------------------------------------------------------------------
#  Platform
# ---------------------------------------------------------------------------
class PlatformResponse(BaseModel):
    id: UUID
    name: str
    platform_type: str
    endpoint_url: str | None = None
    config_json: dict = {}
    is_active: bool
    market_hours: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlatformCreateRequest(BaseModel):
    name: str = Field(..., max_length=100)
    platform_type: str = Field(..., max_length=50)
    endpoint_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = None
    api_secret: str | None = None
    config_json: dict = {}
    market_hours: str = "24h"


class PlatformUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    endpoint_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = None
    api_secret: str | None = None
    config_json: dict | None = None
    market_hours: str | None = None
    is_active: bool | None = None


class PlatformAccountResponse(BaseModel):
    balance: float = 0
    equity: float = 0
    margin: float = 0
    free_margin: float = 0
    currency: str = "USD"
    leverage: int = 0


# ---------------------------------------------------------------------------
#  Analytics summary (dashboard overview)
# ---------------------------------------------------------------------------
class TradeSummary(BaseModel):
    total_trades: int = 0
    open_trades: int = 0
    closed_trades: int = 0
    total_profit: float = 0
    today_profit: float = 0
    win_rate: float = 0
    avg_profit: float = 0
    avg_loss: float = 0
    best_trade: float = 0
    worst_trade: float = 0
