"""
AI Providers API – CRUD, test connection, activate, run analysis.
"""

import uuid as uuid_mod
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user, require_role
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.security import encrypt_value
from app.models.ai_analysis import AiAnalysisLog
from app.models.ai_provider import AiProvider
from app.models.user import User
from app.schemas.ai_provider import (
    AiAnalysisLogResponse,
    AiAnalysisRequest,
    AiProviderCreateRequest,
    AiProviderResponse,
    AiProviderTestResponse,
    AiProviderUpdateRequest,
)
from app.services.ai.registry import create_ai_provider, list_provider_types
from app.services.platforms.registry import create_platform as create_platform_adapter
from app.models.platform import TradingPlatform

router = APIRouter(prefix="/ai-providers", tags=["AI Providers"])


# ---------------------------------------------------------------------------
#  GET /ai-providers
# ---------------------------------------------------------------------------
@router.get("", response_model=list[AiProviderResponse])
async def list_providers(
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AiProvider).order_by(AiProvider.created_at.desc())
    )
    return [AiProviderResponse.model_validate(p) for p in result.scalars().all()]


# ---------------------------------------------------------------------------
#  GET /ai-providers/types
# ---------------------------------------------------------------------------
@router.get("/types", response_model=list[str])
async def get_provider_types(user: User = Depends(get_current_user)):
    return list_provider_types()


# ---------------------------------------------------------------------------
#  GET /ai-providers/analysis-logs
#  (must be before /{provider_id} to avoid path conflict)
# ---------------------------------------------------------------------------
@router.get("/analysis-logs", response_model=list[AiAnalysisLogResponse])
async def list_analysis_logs(
    provider_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    q = select(AiAnalysisLog).order_by(AiAnalysisLog.created_at.desc())
    if provider_id:
        q = q.where(AiAnalysisLog.ai_provider_id == provider_id)
    if symbol:
        q = q.where(AiAnalysisLog.symbol == symbol.upper())

    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    return [AiAnalysisLogResponse.model_validate(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
#  POST /ai-providers/analyze  (story 3.9, 3.10)
#  (must be before /{provider_id} to avoid path conflict)
# ---------------------------------------------------------------------------
@router.post("/analyze", response_model=AiAnalysisLogResponse)
async def run_analysis(
    req: AiAnalysisRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    # Get active provider
    result = await db.execute(
        select(AiProvider).where(AiProvider.is_active == True)  # noqa: E712
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise BadRequestError("No active AI provider configured")

    # Get platform price
    platform_row = await db.execute(
        select(TradingPlatform).where(TradingPlatform.id == str(req.platform_id))
    )
    platform = platform_row.scalar_one_or_none()
    if not platform:
        raise NotFoundError("Platform")

    try:
        adapter = create_platform_adapter(platform)
        price = await adapter.get_price(req.symbol)
        if not price:
            raise BadRequestError(f"Could not fetch price for {req.symbol}")
    except BadRequestError:
        raise
    except Exception:
        raise BadRequestError(f"Platform connection failed while fetching {req.symbol}")

    # Run AI analysis
    correlation_id = str(uuid_mod.uuid4())[:8]
    ai_adapter = create_ai_provider(provider)
    ai_result = await ai_adapter.analyze(req.symbol, price["bid"], price["ask"])

    # Log to DB (story 3.10)
    log = AiAnalysisLog(
        ai_provider_id=provider.id,
        platform_id=platform.id,
        symbol=req.symbol,
        bid=price["bid"],
        ask=price["ask"],
        ai_recommendation=ai_result.reason,
        sentiment=ai_result.sentiment,
        trade_action=ai_result.action,
        latency_ms=ai_result.latency_ms,
        correlation_id=correlation_id,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    return AiAnalysisLogResponse.model_validate(log)


# ---------------------------------------------------------------------------
#  POST /ai-providers  (admin only)
# ---------------------------------------------------------------------------
@router.post("", response_model=AiProviderResponse, status_code=201)
async def create_provider(
    req: AiProviderCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin")),
):
    known = list_provider_types()
    if req.provider_type not in known:
        raise BadRequestError(
            f"Unknown provider type '{req.provider_type}'. Valid: {known}"
        )

    provider = AiProvider(
        name=req.name,
        provider_type=req.provider_type,
        endpoint_url=req.endpoint_url,
        model=req.model,
        api_key_enc=encrypt_value(req.api_key),
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        config_json=req.config_json,
        is_active=False,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return AiProviderResponse.model_validate(provider)


# ---------------------------------------------------------------------------
#  GET /ai-providers/{id}
# ---------------------------------------------------------------------------
@router.get("/{provider_id}", response_model=AiProviderResponse)
async def get_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    provider = await _get_provider_or_404(db, provider_id)
    return AiProviderResponse.model_validate(provider)


# ---------------------------------------------------------------------------
#  PUT /ai-providers/{id}  (admin only)
# ---------------------------------------------------------------------------
@router.put("/{provider_id}", response_model=AiProviderResponse)
async def update_provider(
    provider_id: str,
    req: AiProviderUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin")),
):
    provider = await _get_provider_or_404(db, provider_id)

    for field in ("name", "endpoint_url", "model", "max_tokens", "temperature", "config_json"):
        val = getattr(req, field)
        if val is not None:
            setattr(provider, field, val)

    if req.api_key is not None:
        provider.api_key_enc = encrypt_value(req.api_key)

    await db.commit()
    await db.refresh(provider)
    return AiProviderResponse.model_validate(provider)


# ---------------------------------------------------------------------------
#  DELETE /ai-providers/{id}  (admin only)
# ---------------------------------------------------------------------------
@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin")),
):
    provider = await _get_provider_or_404(db, provider_id)
    if provider.is_active:
        raise BadRequestError("Cannot delete the active provider. Deactivate or switch first.")
    await db.delete(provider)
    await db.commit()


# ---------------------------------------------------------------------------
#  POST /ai-providers/{id}/test  (story 3.7)
# ---------------------------------------------------------------------------
@router.post("/{provider_id}/test", response_model=AiProviderTestResponse)
async def test_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    provider = await _get_provider_or_404(db, provider_id)

    try:
        adapter = create_ai_provider(provider)
        is_healthy, latency_ms = await adapter.health_check()
    except Exception as exc:
        return AiProviderTestResponse(
            is_healthy=False, latency_ms=0, message=str(exc)
        )

    # Update health stats in DB
    provider.last_health_at = datetime.now(timezone.utc)
    if is_healthy:
        # Rolling average: keep 80% old + 20% new
        old = provider.avg_latency_ms or latency_ms
        provider.avg_latency_ms = int(old * 0.8 + latency_ms * 0.2)

    await db.commit()

    return AiProviderTestResponse(
        is_healthy=is_healthy,
        latency_ms=latency_ms,
        message="Connection successful" if is_healthy else "Health check failed",
    )


# ---------------------------------------------------------------------------
#  PUT /ai-providers/{id}/activate
# ---------------------------------------------------------------------------
@router.put("/{provider_id}/activate", response_model=AiProviderResponse)
async def activate_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(require_role("admin")),
):
    provider = await _get_provider_or_404(db, provider_id)

    # Deactivate all others
    result = await db.execute(
        select(AiProvider).where(AiProvider.is_active == True)  # noqa: E712
    )
    for p in result.scalars().all():
        p.is_active = False

    provider.is_active = True
    await db.commit()
    await db.refresh(provider)
    return AiProviderResponse.model_validate(provider)


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
async def _get_provider_or_404(db: AsyncSession, provider_id: str) -> AiProvider:
    result = await db.execute(
        select(AiProvider).where(AiProvider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise NotFoundError("AI Provider")
    return provider
