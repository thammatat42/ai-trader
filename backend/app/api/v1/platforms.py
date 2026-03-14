"""
Trading Platforms API – CRUD, test connection, account info.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user, require_role
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.security import encrypt_value
from app.models.platform import TradingPlatform
from app.models.user import User
from app.schemas.trade import (
    PlatformAccountResponse,
    PlatformCreateRequest,
    PlatformResponse,
    PlatformUpdateRequest,
)
from app.services.platforms.registry import create_platform, list_platform_types

router = APIRouter(prefix="/platforms", tags=["Platforms"])


# ---------------------------------------------------------------------------
#  GET /platforms
# ---------------------------------------------------------------------------
@router.get("", response_model=list[PlatformResponse])
async def list_platforms(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TradingPlatform).order_by(TradingPlatform.created_at.desc())
    )
    return [PlatformResponse.model_validate(p) for p in result.scalars().all()]


# ---------------------------------------------------------------------------
#  GET /platforms/types
# ---------------------------------------------------------------------------
@router.get("/types", response_model=list[str])
async def get_platform_types(user: User = Depends(get_current_user)):
    return list_platform_types()


# ---------------------------------------------------------------------------
#  POST /platforms  (admin only)
# ---------------------------------------------------------------------------
@router.post("", response_model=PlatformResponse, status_code=201)
async def create_platform_endpoint(
    req: PlatformCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin")),
):
    platform = TradingPlatform(
        name=req.name,
        platform_type=req.platform_type,
        endpoint_url=req.endpoint_url,
        api_key_enc=encrypt_value(req.api_key) if req.api_key else None,
        api_secret_enc=encrypt_value(req.api_secret) if req.api_secret else None,
        config_json=req.config_json,
        market_hours=req.market_hours,
        is_active=False,
    )
    db.add(platform)
    await db.commit()
    await db.refresh(platform)
    return PlatformResponse.model_validate(platform)


# ---------------------------------------------------------------------------
#  GET /platforms/{id}
# ---------------------------------------------------------------------------
@router.get("/{platform_id}", response_model=PlatformResponse)
async def get_platform(
    platform_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TradingPlatform).where(TradingPlatform.id == platform_id)
    )
    platform = result.scalar_one_or_none()
    if not platform:
        raise NotFoundError("Platform not found")
    return PlatformResponse.model_validate(platform)


# ---------------------------------------------------------------------------
#  PUT /platforms/{id}  (admin only)
# ---------------------------------------------------------------------------
@router.put("/{platform_id}", response_model=PlatformResponse)
async def update_platform(
    platform_id: str,
    req: PlatformUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(TradingPlatform).where(TradingPlatform.id == platform_id)
    )
    platform = result.scalar_one_or_none()
    if not platform:
        raise NotFoundError("Platform not found")

    if req.name is not None:
        platform.name = req.name
    if req.endpoint_url is not None:
        platform.endpoint_url = req.endpoint_url
    if req.api_key is not None:
        platform.api_key_enc = encrypt_value(req.api_key)
    if req.api_secret is not None:
        platform.api_secret_enc = encrypt_value(req.api_secret)
    if req.config_json is not None:
        platform.config_json = req.config_json
    if req.market_hours is not None:
        platform.market_hours = req.market_hours
    if req.is_active is not None:
        platform.is_active = req.is_active

    await db.commit()
    await db.refresh(platform)
    return PlatformResponse.model_validate(platform)


# ---------------------------------------------------------------------------
#  DELETE /platforms/{id}  (admin only)
# ---------------------------------------------------------------------------
@router.delete("/{platform_id}", status_code=204)
async def delete_platform(
    platform_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin")),
):
    result = await db.execute(
        select(TradingPlatform).where(TradingPlatform.id == platform_id)
    )
    platform = result.scalar_one_or_none()
    if not platform:
        raise NotFoundError("Platform not found")
    await db.delete(platform)
    await db.commit()


# ---------------------------------------------------------------------------
#  POST /platforms/{id}/test  —  test connection + health check
# ---------------------------------------------------------------------------
@router.post("/{platform_id}/test")
async def test_platform(
    platform_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TradingPlatform).where(TradingPlatform.id == platform_id)
    )
    platform = result.scalar_one_or_none()
    if not platform:
        raise NotFoundError("Platform not found")

    try:
        adapter = create_platform(platform)
        is_healthy, latency_ms = await adapter.health_check()
        return {
            "connected": is_healthy,
            "latency_ms": latency_ms,
            "platform_type": platform.platform_type,
        }
    except Exception as e:
        return {"connected": False, "latency_ms": 0, "error": str(e)}


# ---------------------------------------------------------------------------
#  GET /platforms/{id}/account  —  account info from platform
# ---------------------------------------------------------------------------
@router.get("/{platform_id}/account", response_model=PlatformAccountResponse)
async def get_account(
    platform_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TradingPlatform).where(TradingPlatform.id == platform_id)
    )
    platform = result.scalar_one_or_none()
    if not platform:
        raise NotFoundError("Platform not found")
    if not platform.is_active:
        raise BadRequestError("Platform is not active")

    try:
        adapter = create_platform(platform)
        account = await adapter.get_account()
        return PlatformAccountResponse(
            balance=account.get("balance", 0),
            equity=account.get("equity", 0),
            margin=account.get("margin", 0),
            free_margin=account.get("free_margin", 0),
            currency=account.get("currency", "USD"),
            leverage=account.get("leverage", 0),
        )
    except Exception as e:
        raise BadRequestError(f"Failed to get account: {e}")


# ---------------------------------------------------------------------------
#  GET /platforms/{id}/price/{symbol}
# ---------------------------------------------------------------------------
@router.get("/{platform_id}/price/{symbol}")
async def get_price(
    platform_id: str,
    symbol: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TradingPlatform).where(TradingPlatform.id == platform_id)
    )
    platform = result.scalar_one_or_none()
    if not platform:
        raise NotFoundError("Platform not found")

    adapter = create_platform(platform)
    price = await adapter.get_price(symbol)
    if not price:
        raise BadRequestError(f"Could not get price for {symbol}")
    return {"symbol": price.symbol, "bid": price.bid, "ask": price.ask, "timestamp": price.timestamp}
