"""
Trade service – risk calculation, lot sizing, SL/TP, trade execution,
and market hours checking.
"""

import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade import Trade
from app.models.platform import TradingPlatform
from app.services.platforms.base import PriceData, TradeResult
from app.services.platforms.registry import create_platform


# ---------------------------------------------------------------------------
#  Market Hours
# ---------------------------------------------------------------------------
def is_forex_market_open() -> tuple[bool, str]:
    """
    Check if XAUUSD / Forex market is open (UTC-based).
    Returns (is_open, reason).
    """
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Mon .. 6=Sun
    hour = now.hour

    if weekday == 5:
        return False, "Saturday – market closed"
    if weekday == 6 and hour < 23:
        return False, f"Sunday {hour:02d}:{now.minute:02d} UTC – opens 23:00 UTC"
    if weekday == 4 and hour >= 22:
        return False, f"Friday {hour:02d}:{now.minute:02d} UTC – closed for weekend"
    if hour == 22:
        return False, f"Daily break {hour:02d}:{now.minute:02d} UTC – reopens 23:00"
    return True, "Market is open"


def is_market_open(market_type: str) -> tuple[bool, str]:
    """Dispatch by market type."""
    if market_type == "forex":
        return is_forex_market_open()
    # Crypto markets (bitkub, binance) are 24/7
    return True, "24h market"


# ---------------------------------------------------------------------------
#  Risk / Lot / SL / TP
# ---------------------------------------------------------------------------
def calculate_lot_size(
    balance: float,
    risk_percent: float,
    sl_points: float,
) -> float:
    """
    Lot = (balance × risk%) / SL_points.
    Clamp to >= 0.01 (minimum forex lot).
    """
    if sl_points <= 0:
        return 0.01
    risk_amount = balance * (risk_percent / 100.0)
    raw_lot = risk_amount / sl_points
    return max(0.01, round(raw_lot, 2))


def calculate_sl_tp(
    action: str,
    entry_price: float,
    sl_points: float,
    tp_points: float,
    point_value: float = 0.01,
) -> tuple[float, float]:
    """
    Computes SL and TP prices for a given action, entry price, and point distances.
    point_value = 0.01 for XAUUSD (1 point = $0.01 per unit).
    Returns (sl_price, tp_price).
    """
    if action.upper() == "BUY":
        sl = round(entry_price - sl_points * point_value, 8)
        tp = round(entry_price + tp_points * point_value, 8)
    else:  # SELL
        sl = round(entry_price + sl_points * point_value, 8)
        tp = round(entry_price - tp_points * point_value, 8)
    return sl, tp


# ---------------------------------------------------------------------------
#  Trade Execution (one-shot via platform adapter)
# ---------------------------------------------------------------------------
async def execute_trade(
    platform: TradingPlatform,
    action: str,
    symbol: str,
    lot: float,
    sl_price: float,
    tp_price: float,
) -> TradeResult:
    """Creates the adapter and fires a trade."""
    adapter = create_platform(platform)
    return await adapter.execute_trade(action, symbol, lot, sl_price, tp_price)


# ---------------------------------------------------------------------------
#  Fetch helpers (positions, history, account) via adapter
# ---------------------------------------------------------------------------
async def get_platform_positions(platform: TradingPlatform) -> list[dict]:
    adapter = create_platform(platform)
    return await adapter.get_positions()


async def get_platform_history(platform: TradingPlatform, days: int = 7) -> list[dict]:
    adapter = create_platform(platform)
    return await adapter.get_history(days=days)


async def get_platform_account(platform: TradingPlatform) -> dict:
    adapter = create_platform(platform)
    return await adapter.get_account()


async def get_platform_price(
    platform: TradingPlatform, symbol: str
) -> PriceData | None:
    adapter = create_platform(platform)
    return await adapter.get_price(symbol)


# ---------------------------------------------------------------------------
#  DB trade helpers
# ---------------------------------------------------------------------------
async def count_trades_today(
    db: AsyncSession, platform_id: uuid.UUID | None = None
) -> int:
    """Count trades opened today (UTC)."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    q = select(func.count()).select_from(Trade).where(Trade.opened_at >= today_start)
    if platform_id:
        q = q.where(Trade.platform_id == platform_id)
    result = await db.execute(q)
    return result.scalar() or 0


async def create_trade_record(
    db: AsyncSession,
    *,
    platform_id: uuid.UUID | None,
    order_id: str | None,
    symbol: str,
    action: str,
    lot: float,
    open_price: float | None,
    sl_price: float | None,
    tp_price: float | None,
    ai_provider_id: uuid.UUID | None = None,
    ai_analysis_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> Trade:
    """Insert a new OPEN trade."""
    trade = Trade(
        platform_id=platform_id,
        order_id=order_id,
        symbol=symbol,
        action=action.upper(),
        lot=lot,
        open_price=open_price,
        sl_price=sl_price,
        tp_price=tp_price,
        status="OPEN",
        ai_provider_id=ai_provider_id,
        ai_analysis_id=ai_analysis_id,
        user_id=user_id,
    )
    db.add(trade)
    await db.flush()
    return trade


async def close_trade_record(
    db: AsyncSession,
    trade: Trade,
    close_price: float,
    profit: float,
    commission: float = 0,
    swap: float = 0,
) -> Trade:
    """Mark a trade as CLOSED."""
    trade.close_price = close_price
    trade.profit = profit
    trade.commission = commission
    trade.swap = swap
    trade.status = "CLOSED"
    trade.closed_at = datetime.now(timezone.utc)
    await db.flush()
    return trade
