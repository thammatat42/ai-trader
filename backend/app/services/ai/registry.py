"""
AI Provider registry – factory that instantiates the right provider from DB config.
"""

from app.core.security import decrypt_value
from app.models.ai_provider import AiProvider
from app.services.ai.base import BaseAIProvider
from app.services.ai.nvidia_nim import NvidiaNimProvider
from app.services.ai.openrouter import OpenRouterProvider

_PROVIDERS: dict[str, type[BaseAIProvider]] = {
    "openrouter": OpenRouterProvider,
    "nvidia_nim": NvidiaNimProvider,
}


def create_ai_provider(config: AiProvider) -> BaseAIProvider:
    """Create an AI provider instance from a database config row."""
    cls = _PROVIDERS.get(config.provider_type)
    if not cls:
        raise ValueError(f"Unknown AI provider type: {config.provider_type}")

    api_key = decrypt_value(config.api_key_enc) if config.api_key_enc else ""

    return cls(
        api_key=api_key,
        endpoint_url=config.endpoint_url,
        model=config.model,
        max_tokens=config.max_tokens,
        temperature=float(config.temperature),
    )


def list_provider_types() -> list[str]:
    return list(_PROVIDERS.keys())
