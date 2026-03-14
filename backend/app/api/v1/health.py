"""Health check endpoint – no auth required."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.redis import check_redis_health
from app.schemas.common import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    settings = get_settings()

    # Check DB connectivity
    db_ok = True
    try:
        from app.core.database import engine
        from sqlalchemy import text

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    # Check Redis connectivity
    redis_ok = await check_redis_health()

    return HealthResponse(
        status="healthy" if (db_ok and redis_ok) else "degraded",
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        db=db_ok,
        redis=redis_ok,
    )
