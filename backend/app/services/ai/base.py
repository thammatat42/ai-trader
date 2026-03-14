"""
Abstract base class for all AI providers.
Each provider must implement analyze() and health_check().
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class AIAnalysisResult(BaseModel):
    sentiment: str       # "BULLISH" | "BEARISH" | "NEUTRAL"
    action: str          # "BUY" | "SELL" | "WAIT"
    reason: str
    raw_response: str
    latency_ms: int
    provider_name: str
    model: str


class BaseAIProvider(ABC):
    @abstractmethod
    async def analyze(
        self, symbol: str, bid: float, ask: float, context: dict | None = None
    ) -> AIAnalysisResult:
        ...

    @abstractmethod
    async def health_check(self) -> tuple[bool, int]:
        """Returns (is_healthy, latency_ms)."""
        ...

    @abstractmethod
    def provider_type(self) -> str:
        ...
