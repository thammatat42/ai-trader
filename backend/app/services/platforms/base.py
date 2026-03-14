"""
Abstract base class for all trading platform adapters.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class PriceData(BaseModel):
    symbol: str
    bid: float
    ask: float
    timestamp: int


class TradeResult(BaseModel):
    success: bool
    order_id: str | None = None
    price: float | None = None
    error: str | None = None


class BasePlatform(ABC):
    @abstractmethod
    async def get_price(self, symbol: str) -> PriceData | None:
        ...

    @abstractmethod
    async def execute_trade(
        self, action: str, symbol: str, lot: float, sl: float, tp: float
    ) -> TradeResult:
        ...

    @abstractmethod
    async def get_positions(self) -> list[dict]:
        ...

    @abstractmethod
    async def get_history(self, days: int = 7) -> list[dict]:
        ...

    @abstractmethod
    async def get_account(self) -> dict:
        ...

    @abstractmethod
    async def health_check(self) -> tuple[bool, int]:
        """Returns (is_healthy, latency_ms)."""
        ...

    @abstractmethod
    def platform_type(self) -> str:
        ...

    @abstractmethod
    def market_hours_type(self) -> str:
        """Return 'forex' or '24h'."""
        ...
