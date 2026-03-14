"""
Redis-backed rate limiting middleware.
Applies per-IP sliding-window rate limits to all API requests.
Auth endpoints get a stricter limit to prevent brute-force attacks.
"""

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.redis import get_redis

logger = structlog.get_logger("rate_limit")

# Paths that get the stricter auth rate limit
_AUTH_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/refresh"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health checks and non-API routes
        path = request.url.path
        if not path.startswith("/api/") or path == "/api/v1/health":
            return await call_next(request)

        settings = get_settings()
        client_ip = request.client.host if request.client else "unknown"

        # Choose limit based on path
        if path in _AUTH_PATHS:
            limit = settings.RATE_LIMIT_AUTH_PER_MINUTE
            key = f"rl:auth:{client_ip}"
        else:
            limit = settings.RATE_LIMIT_PER_MINUTE
            key = f"rl:api:{client_ip}"

        redis = get_redis()
        window = 60  # 1 minute window

        try:
            now = time.time()
            pipe = redis.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, now - window)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Count requests in window
            pipe.zcard(key)
            # Set expiry on the key
            pipe.expire(key, window)
            results = await pipe.execute()
            request_count = results[2]
        except Exception:
            # If Redis is down, allow the request (fail-open for availability)
            logger.warning("rate_limit_redis_error", client_ip=client_ip)
            return await call_next(request)

        # Add rate limit headers
        response = await call_next(request) if request_count <= limit else JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."},
        )

        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - request_count))
        response.headers["X-RateLimit-Reset"] = str(window)

        if request_count > limit:
            logger.warning("rate_limit_exceeded", client_ip=client_ip, path=path, count=request_count)

        return response
