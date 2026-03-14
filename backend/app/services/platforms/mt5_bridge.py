"""
MT5 Bridge adapter – connects to the Windows VPS FastAPI bridge.
"""

import time

import httpx

from app.services.platforms.base import BasePlatform, PriceData, TradeResult


class MT5BridgePlatform(BasePlatform):
    def __init__(self, endpoint_url: str, config: dict | None = None):
        self._base_url = endpoint_url.rstrip("/")
        self._config = config or {}
        self._timeout = self._config.get("timeout", 10)

    async def get_price(self, symbol: str) -> PriceData | None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/price/{symbol}")
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                return None
            return PriceData(
                symbol=symbol,
                bid=data["bid"],
                ask=data["ask"],
                timestamp=data.get("time", 0),
            )

    async def execute_trade(
        self, action: str, symbol: str, lot: float, sl: float, tp: float
    ) -> TradeResult:
        payload = {"action": action, "symbol": symbol, "lot": lot, "sl": sl, "tp": tp}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/trade", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return TradeResult(
                success=data.get("success", False),
                order_id=str(data.get("order_id")) if data.get("order_id") else None,
                price=data.get("price"),
                error=data.get("error"),
            )

    async def get_positions(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/positions")
            resp.raise_for_status()
            return resp.json().get("positions", [])

    async def get_history(self, days: int = 7) -> list[dict]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/history", params={"days": days})
            resp.raise_for_status()
            return resp.json().get("deals", [])

    async def get_account(self) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}/account")
            resp.raise_for_status()
            return resp.json()

    async def health_check(self) -> tuple[bool, int]:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/")
                latency_ms = int((time.perf_counter() - start) * 1000)
                data = resp.json()
                return data.get("mt5_connected", False), latency_ms
        except Exception:
            return False, int((time.perf_counter() - start) * 1000)

    def platform_type(self) -> str:
        return "mt5"

    def market_hours_type(self) -> str:
        return "forex"
