"""
Auth API endpoints – register, login, refresh, logout, API key management.
"""

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.dependencies import get_current_user
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.geo import resolve_ip_geo
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    get_api_key_prefix,
    hash_password,
    verify_password,
)
from app.models.api_key import ApiKey
from app.models.login_activity import LoginActivity
from app.models.plan import Plan
from app.models.user import User
from app.models.user_subscription import UserSubscription
from app.schemas.auth import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.common import MessageResponse

logger = structlog.get_logger("auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# ---- Token blocklist helpers ----
_BLOCKLIST_PREFIX = "token:blocked:"


async def _block_token(jti: str, ttl_seconds: int) -> None:
    """Add a token (by its JTI/sub+exp combo) to the Redis blocklist."""
    redis = get_redis()
    await redis.setex(f"{_BLOCKLIST_PREFIX}{jti}", ttl_seconds, "1")


async def _is_token_blocked(jti: str) -> bool:
    redis = get_redis()
    return await redis.exists(f"{_BLOCKLIST_PREFIX}{jti}") > 0


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db_session)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    # First user becomes admin; subsequent users get "trader"
    user_count = await db.scalar(select(func.count()).select_from(User))
    role = "admin" if user_count == 0 else "trader"

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=role,
    )
    db.add(user)
    await db.flush()

    # Auto-subscribe to the default (free) plan and grant signup credits
    default_plan_result = await db.execute(
        select(Plan).where(Plan.is_default.is_(True), Plan.is_active.is_(True)).limit(1)
    )
    default_plan = default_plan_result.scalar_one_or_none()
    if default_plan:
        sub = UserSubscription(
            user_id=user.id,
            plan_id=default_plan.id,
            billing_cycle="monthly",
            status="active",
        )
        db.add(sub)

        if default_plan.ai_credits_monthly > 0:
            from app.core.access_control import grant_credits
            await grant_credits(
                db, user.id, default_plan.ai_credits_monthly,
                tx_type="signup_bonus",
                description=f"Welcome bonus: {default_plan.ai_credits_monthly} free AI credits",
            )

    await db.commit()
    await db.refresh(user)
    return user


async def _record_login(
    db: AsyncSession,
    *,
    user_id: str | None,
    email: str,
    ip_address: str,
    user_agent: str | None,
    success: bool,
    failure_reason: str | None = None,
) -> None:
    """Record a login attempt with IP geolocation."""
    country, city = await resolve_ip_geo(ip_address)
    activity = LoginActivity(
        user_id=user_id,
        email=email,
        ip_address=ip_address,
        user_agent=user_agent,
        country=country,
        city=city,
        success=success,
        failure_reason=failure_reason,
    )
    db.add(activity)
    await db.commit()
    logger.info(
        "login_attempt",
        email=email,
        success=success,
        ip=ip_address,
        country=country,
        reason=failure_reason,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db_session)):
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # User not found
    if not user:
        await _record_login(
            db, user_id=None, email=body.email, ip_address=client_ip,
            user_agent=user_agent, success=False, failure_reason="user_not_found",
        )
        raise UnauthorizedError("Invalid email or password")

    # Banned check
    if user.is_banned:
        await _record_login(
            db, user_id=str(user.id), email=body.email, ip_address=client_ip,
            user_agent=user_agent, success=False, failure_reason="banned",
        )
        raise UnauthorizedError("Account has been banned")

    # Inactive check
    if not user.is_active:
        await _record_login(
            db, user_id=str(user.id), email=body.email, ip_address=client_ip,
            user_agent=user_agent, success=False, failure_reason="inactive",
        )
        raise UnauthorizedError("Account is disabled")

    # Locked check
    if user.is_locked:
        await _record_login(
            db, user_id=str(user.id), email=body.email, ip_address=client_ip,
            user_agent=user_agent, success=False, failure_reason="locked",
        )
        raise UnauthorizedError("Account is temporarily locked. Try again later.")

    # Password check
    if not verify_password(body.password, user.hashed_password):
        user.failed_login_count += 1
        # Lock account after N failures
        if user.failed_login_count >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_MINUTES
            )
            logger.warning(
                "account_locked",
                user_id=str(user.id),
                failed_attempts=user.failed_login_count,
            )
        await db.commit()
        await _record_login(
            db, user_id=str(user.id), email=body.email, ip_address=client_ip,
            user_agent=user_agent, success=False, failure_reason="invalid_password",
        )
        raise UnauthorizedError("Invalid email or password")

    # Success – reset counters
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    await _record_login(
        db, user_id=str(user.id), email=body.email, ip_address=client_ip,
        user_agent=user_agent, success=True,
    )

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db_session)):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid refresh token")

    # Check if refresh token is blocklisted
    token_jti = f"{payload.get('sub')}:{payload.get('exp')}"
    if await _is_token_blocked(token_jti):
        raise UnauthorizedError("Token has been revoked")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise UnauthorizedError("User not found or disabled")

    # Block the old refresh token (rotation)
    settings = get_settings()
    await _block_token(token_jti, settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400)

    new_access = create_access_token({"sub": str(user.id)})
    new_refresh = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
):
    # Block the access token currently in use
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = decode_token(token)
        if payload:
            token_jti = f"{payload.get('sub')}:{payload.get('exp')}"
            settings = get_settings()
            await _block_token(token_jti, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60)

    return MessageResponse(message="Logged out successfully")


# ---- API Key Management ----

api_keys_router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@api_keys_router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@api_keys_router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    full_key, key_hash = generate_api_key()

    api_key = ApiKey(
        user_id=user.id,
        name=body.name,
        key_prefix=get_api_key_prefix(full_key),
        key_hash=key_hash,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        full_key=full_key,
    )


@api_keys_router.delete("/{key_id}", response_model=MessageResponse)
async def revoke_api_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("API key")

    api_key.is_active = False
    await db.commit()
    return MessageResponse(message="API key revoked")
