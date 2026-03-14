"""
Auth API endpoints – register, login, refresh, logout, API key management.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.dependencies import get_current_user
from app.core.exceptions import ConflictError, UnauthorizedError
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
from app.models.user import User
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
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")

    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

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
