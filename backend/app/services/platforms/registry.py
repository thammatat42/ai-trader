"""
Platform registry – factory that instantiates the right adapter from DB config.
"""

from app.core.security import decrypt_value
from app.models.platform import TradingPlatform
from app.services.platforms.base import BasePlatform
from app.services.platforms.mt5_bridge import MT5BridgePlatform

_PLATFORMS: dict[str, type[BasePlatform]] = {
    "mt5": MT5BridgePlatform,
}


def create_platform(config: TradingPlatform) -> BasePlatform:
    """Create a platform adapter instance from a database config row."""
    cls = _PLATFORMS.get(config.platform_type)
    if not cls:
        raise ValueError(f"Unknown platform type: {config.platform_type}")

    endpoint = config.endpoint_url or ""

    if config.platform_type == "mt5":
        return cls(endpoint_url=endpoint, config=config.config_json)

    # For crypto platforms (bitkub, binance) – will be added in Epic 7
    api_key = decrypt_value(config.api_key_enc) if config.api_key_enc else ""
    api_secret = decrypt_value(config.api_secret_enc) if config.api_secret_enc else ""

    return cls(
        api_key=api_key,
        api_secret=api_secret,
        endpoint_url=endpoint,
        config=config.config_json,
    )


def list_platform_types() -> list[str]:
    return list(_PLATFORMS.keys())
