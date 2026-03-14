"""
Trades API – list trades, open positions, history, manual trade execution.
"""

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.platform import TradingPlatform
from app.models.trade import Trade
from app.models.user import User
from app.schemas.trade import (
    ManualTradeRequest,
    PlatformAccountResponse,
    TradeResponse,
    TradeSummary,
)
from app.services.trade_service import (
    count_trades_today,
    create_trade_record,
    execute_trade,
    get_platform_account,
    get_platform_positions,
    is_market_open,
)

router = APIRouter(prefix="/trades", tags=["Trades"])


# ---------------------------------------------------------------------------
#  GET /trades  —  paginated trade list (filter by status/platform/symbol)
# ---------------------------------------------------------------------------
@router.get("", response_model=dict)
async def list_trades(
    status: str | None = Query(None, description="OPEN, CLOSED"),
    platform_id: str | None = Query(None),
    symbol: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    q = select(Trade).order_by(Trade.opened_at.desc())
    count_q = select(func.count()).select_from(Trade)

    if status:
        q = q.where(Trade.status == status.upper())
        count_q = count_q.where(Trade.status == status.upper())
    if platform_id:
        q = q.where(Trade.platform_id == platform_id)
        count_q = count_q.where(Trade.platform_id == platform_id)
    if symbol:
        q = q.where(Trade.symbol == symbol.upper())
        count_q = count_q.where(Trade.symbol == symbol.upper())

    total = (await db.execute(count_q)).scalar() or 0
    pages = math.ceil(total / per_page) if total else 0
    offset = (page - 1) * per_page

    result = await db.execute(q.offset(offset).limit(per_page))
    trades = result.scalars().all()

    return {
        "items": [TradeResponse.model_validate(t) for t in trades],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


# ---------------------------------------------------------------------------
#  GET /trades/positions  —  open positions (from DB)
# ---------------------------------------------------------------------------
@router.get("/positions", response_model=list[TradeResponse])
async def get_positions(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Trade)
        .where(Trade.status == "OPEN")
        .order_by(Trade.opened_at.desc())
    )
    return [TradeResponse.model_validate(t) for t in result.scalars().all()]


# ---------------------------------------------------------------------------
#  GET /trades/history  —  closed trades
# ---------------------------------------------------------------------------
@router.get("/history", response_model=dict)
async def get_history(
    platform_id: str | None = Query(None),
    symbol: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    q = (
        select(Trade)
        .where(Trade.status == "CLOSED")
        .order_by(Trade.closed_at.desc())
    )
    count_q = select(func.count()).select_from(Trade).where(Trade.status == "CLOSED")

    if platform_id:
        q = q.where(Trade.platform_id == platform_id)
        count_q = count_q.where(Trade.platform_id == platform_id)
    if symbol:
        q = q.where(Trade.symbol == symbol.upper())
        count_q = count_q.where(Trade.symbol == symbol.upper())

    total = (await db.execute(count_q)).scalar() or 0
    pages = math.ceil(total / per_page) if total else 0
    offset = (page - 1) * per_page

    result = await db.execute(q.offset(offset).limit(per_page))
    trades = result.scalars().all()

    return {
        "items": [TradeResponse.model_validate(t) for t in trades],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
    }


# ---------------------------------------------------------------------------
#  GET /trades/summary  —  trade statistics for dashboard
# ---------------------------------------------------------------------------
@router.get("/summary", response_model=TradeSummary)
async def get_trade_summary(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    # Total / open / closed counts
    total = (
        await db.execute(select(func.count()).select_from(Trade))
    ).scalar() or 0

    open_count = (
        await db.execute(
            select(func.count()).select_from(Trade).where(Trade.status == "OPEN")
        )
    ).scalar() or 0

    closed_count = (
        await db.execute(
            select(func.count()).select_from(Trade).where(Trade.status == "CLOSED")
        )
    ).scalar() or 0

    # Profit aggregates
    total_profit = (
        await db.execute(
            select(func.coalesce(func.sum(Trade.profit), 0)).where(
                Trade.status == "CLOSED"
            )
        )
    ).scalar() or 0

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_profit = (
        await db.execute(
            select(func.coalesce(func.sum(Trade.profit), 0)).where(
                Trade.status == "CLOSED", Trade.closed_at >= today_start
            )
        )
    ).scalar() or 0

    # Win / loss stats
    wins = (
        await db.execute(
            select(func.count()).select_from(Trade).where(
                Trade.status == "CLOSED", Trade.profit > 0
            )
        )
    ).scalar() or 0

    win_rate = (wins / closed_count * 100) if closed_count > 0 else 0

    avg_profit_val = (
        await db.execute(
            select(func.avg(Trade.profit)).where(
                Trade.status == "CLOSED", Trade.profit > 0
            )
        )
    ).scalar() or 0

    avg_loss_val = (
        await db.execute(
            select(func.avg(Trade.profit)).where(
                Trade.status == "CLOSED", Trade.profit < 0
            )
        )
    ).scalar() or 0

    best = (
        await db.execute(
            select(func.max(Trade.profit)).where(Trade.status == "CLOSED")
        )
    ).scalar() or 0

    worst = (
        await db.execute(
            select(func.min(Trade.profit)).where(Trade.status == "CLOSED")
        )
    ).scalar() or 0

    return TradeSummary(
        total_trades=total,
        open_trades=open_count,
        closed_trades=closed_count,
        total_profit=float(total_profit),
        today_profit=float(today_profit),
        win_rate=round(float(win_rate), 1),
        avg_profit=round(float(avg_profit_val), 2),
        avg_loss=round(float(avg_loss_val), 2),
        best_trade=float(best),
        worst_trade=float(worst),
    )


# ---------------------------------------------------------------------------
#  POST /trades  —  manual trade execution
# ---------------------------------------------------------------------------
@router.post("", response_model=TradeResponse, status_code=201)
async def manual_trade(
    req: ManualTradeRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    # Validate platform exists and is active
    result = await db.execute(
        select(TradingPlatform).where(TradingPlatform.id == req.platform_id)
    )
    platform = result.scalar_one_or_none()
    if not platform:
        raise NotFoundError("Platform not found")
    if not platform.is_active:
        raise BadRequestError("Platform is not active")

    # Check market hours
    open_status, reason = is_market_open(platform.market_hours)
    if not open_status:
        raise BadRequestError(f"Market closed: {reason}")

    # Execute via adapter
    trade_result = await execute_trade(
        platform, req.action, req.symbol, req.lot, req.sl_price, req.tp_price
    )

    if not trade_result.success:
        raise BadRequestError(f"Trade failed: {trade_result.error}")

    # Persist to DB
    trade = await create_trade_record(
        db,
        platform_id=platform.id,
        order_id=trade_result.order_id,
        symbol=req.symbol,
        action=req.action,
        lot=req.lot,
        open_price=trade_result.price,
        sl_price=req.sl_price,
        tp_price=req.tp_price,
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(trade)
    return TradeResponse.model_validate(trade)
