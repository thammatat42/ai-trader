"""
IP geolocation utility – resolves IP → country/city using ip-api.com (free tier).
Non-blocking with a short timeout so it never slows down the login flow.
Returns (country, city) or (None, None) on failure.
"""

import httpx
import structlog

logger = structlog.get_logger("geo")

_TIMEOUT = 2.0  # seconds


async def resolve_ip_geo(ip_address: str) -> tuple[str | None, str | None]:
    """Resolve IP address to (country, city). Returns (None, None) on failure."""
    if not ip_address or ip_address in ("127.0.0.1", "::1", "unknown"):
        return None, None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip_address}",
                params={"fields": "status,country,city"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return data.get("country"), data.get("city")
    except Exception:
        logger.debug("geo_lookup_failed", ip=ip_address)
    return None, None
