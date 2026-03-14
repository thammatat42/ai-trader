"""
FastAPI dependency injection: DB session, current user, auth checks.
"""

from datetime import datetime, timezone

from fastapi import Depends, Header, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.redis import get_redis
from app.core.security import decode_token, verify_api_key
from app.models.api_key import ApiKey
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

_BLOCKLIST_PREFIX = "token:blocked:"


async def _is_token_blocked(jti: str) -> bool:
    redis = get_redis()
    return await redis.exists(f"{_BLOCKLIST_PREFIX}{jti}") > 0


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    x_api_key: str | None = Header(None),
) -> User:
    """
    Authenticate via Bearer JWT token OR X-API-Key header.
    Returns the authenticated User model or raises 401.
    """
    # --- Try Bearer JWT first ---
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload and payload.get("type") == "access":
            # Check Redis blocklist
            token_jti = f"{payload.get('sub')}:{payload.get('exp')}"
            if await _is_token_blocked(token_jti):
                raise UnauthorizedError("Token has been revoked")

            user_id = payload.get("sub")
            if user_id:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user and user.is_active and not user.is_banned:
                    return user
                if user and user.is_banned:
                    raise UnauthorizedError("Account has been banned")
        raise UnauthorizedError("Invalid or expired token")

    # --- Try API Key ---
    if x_api_key:
        result = await db.execute(select(ApiKey).where(ApiKey.is_active.is_(True)))
        api_keys = result.scalars().all()
        for ak in api_keys:
            if verify_api_key(x_api_key, ak.key_hash):
                # Update last_used_at
                ak.last_used_at = datetime.now(timezone.utc)
                await db.commit()

                user_result = await db.execute(select(User).where(User.id == ak.user_id))
                user = user_result.scalar_one_or_none()
                if user and user.is_active:
                    return user
        raise UnauthorizedError("Invalid API key")

    raise UnauthorizedError("Authentication required")


def require_role(*roles: str):
    """Dependency factory: require user to have one of the specified roles."""
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError(f"Requires role: {', '.join(roles)}")
        return user
    return _check
