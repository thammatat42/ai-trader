"""
Redis connection pool for caching, pub/sub, rate limiting, and JWT blocklist.
"""

import redis.asyncio as aioredis

from app.core.config import get_settings

settings = get_settings()

redis_pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=20,
    decode_responses=True,
)


def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=redis_pool)


async def check_redis_health() -> bool:
    r = get_redis()
    try:
        return await r.ping()
    except Exception:
        return False
