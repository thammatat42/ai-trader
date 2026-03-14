"""
Trade sync worker – Celery tasks for syncing trades from platforms.

Tasks:
  - sync_trades:  fetch open positions + recent history from each active
    platform and reconcile with the trades table.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.platform import TradingPlatform
from app.models.trade import Trade
from app.services.platforms.registry import create_platform
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from synchronous Celery task context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _sync_platform_trades(platform: TradingPlatform):
    """Sync trades for a single platform."""
    adapter = create_platform(platform)
    async with async_session_factory() as db:
        # ──────────────────────────────────────────
        # 1. Sync open positions (update profit)
        # ──────────────────────────────────────────
        try:
            positions = await adapter.get_positions()
            for pos in positions:
                order_id = str(pos.get("ticket") or pos.get("order_id", ""))
                if not order_id:
                    continue

                result = await db.execute(
                    select(Trade).where(
                        Trade.platform_id == platform.id,
                        Trade.order_id == order_id,
                    )
                )
                trade = result.scalar_one_or_none()

                if trade:
                    # Update live profit
                    trade.profit = pos.get("profit", 0)
                    trade.swap = pos.get("swap", 0)
                    trade.commission = pos.get("commission", 0)
                else:
                    # New position not in DB – insert it
                    trade = Trade(
                        platform_id=platform.id,
                        order_id=order_id,
                        symbol=pos.get("symbol", "UNKNOWN"),
                        action="BUY" if pos.get("type", 0) == 0 else "SELL",
                        lot=pos.get("volume", 0.01),
                        open_price=pos.get("price_open", 0),
                        sl_price=pos.get("sl", 0) or None,
                        tp_price=pos.get("tp", 0) or None,
                        profit=pos.get("profit", 0),
                        commission=pos.get("commission", 0),
                        swap=pos.get("swap", 0),
                        status="OPEN",
                    )
                    db.add(trade)

            logger.info(
                "Synced %d open positions for platform %s",
                len(positions), platform.name,
            )
        except Exception:
            logger.exception("Error syncing positions for %s", platform.name)

        # ──────────────────────────────────────────
        # 2. Sync closed deals (history)
        # ──────────────────────────────────────────
        try:
            history = await adapter.get_history(days=1)
            closed_count = 0

            for deal in history:
                order_id = str(deal.get("ticket") or deal.get("order_id", ""))
                if not order_id:
                    continue

                result = await db.execute(
                    select(Trade).where(
                        Trade.platform_id == platform.id,
                        Trade.order_id == order_id,
                        Trade.status == "OPEN",
                    )
                )
                trade = result.scalar_one_or_none()

                if trade:
                    trade.close_price = deal.get("price", 0)
                    trade.profit = deal.get("profit", 0)
                    trade.commission = deal.get("commission", 0)
                    trade.swap = deal.get("swap", 0)
                    trade.status = "CLOSED"
                    trade.closed_at = datetime.now(timezone.utc)
                    closed_count += 1

            if closed_count:
                logger.info(
                    "Closed %d trades for platform %s",
                    closed_count, platform.name,
                )
        except Exception:
            logger.exception("Error syncing history for %s", platform.name)

        await db.commit()


async def _sync_all_platforms():
    """Iterate all active platforms and sync."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(TradingPlatform).where(TradingPlatform.is_active.is_(True))
        )
        platforms = result.scalars().all()

    for platform in platforms:
        await _sync_platform_trades(platform)


@celery_app.task(name="sync_trades", bind=True, max_retries=3)
def sync_trades(self):
    """Celery task: sync trades from all active platforms."""
    logger.info("Starting trade sync task")
    try:
        _run_async(_sync_all_platforms())
        logger.info("Trade sync completed")
    except Exception as exc:
        logger.exception("Trade sync failed")
        raise self.retry(exc=exc, countdown=30)


# Register periodic beat schedule
celery_app.conf.beat_schedule = {
    **getattr(celery_app.conf, "beat_schedule", {}),
    "sync-trades-every-60s": {
        "task": "sync_trades",
        "schedule": 60.0,
    },
}
