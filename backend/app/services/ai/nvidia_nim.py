"""
NVIDIA NIM AI adapter – Llama 3.1 70B Instruct via NVIDIA API.
Endpoint: https://integrate.api.nvidia.com/v1/chat/completions
"""

import time

import httpx

from app.services.ai.base import AIAnalysisResult, BaseAIProvider

SYSTEM_PROMPT = (
    "Act as pro market analyst. "
    "Reply EXACTLY in this format:\n"
    "Sentiment: <Bullish/Bearish/Neutral>\n"
    "Reason: <1 short sentence>"
)


class NvidiaNimProvider(BaseAIProvider):
    def __init__(
        self,
        api_key: str,
        endpoint_url: str = "https://integrate.api.nvidia.com/v1/chat/completions",
        model: str = "meta/llama-3.1-70b-instruct",
        max_tokens: int = 100,
        temperature: float = 0.1,
    ):
        self._api_key = api_key
        self._endpoint = endpoint_url
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def analyze(
        self, symbol: str, bid: float, ask: float, context: dict | None = None
    ) -> AIAnalysisResult:
        user_prompt = f"Current {symbol} Price -> Bid: {bid}, Ask: {ask}. Analyze sentiment."

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._endpoint, json=payload, headers=headers)
            resp.raise_for_status()

        latency_ms = int((time.perf_counter() - start) * 1000)
        raw = resp.json()["choices"][0]["message"]["content"].strip()

        sentiment, action = self._parse(raw)

        return AIAnalysisResult(
            sentiment=sentiment,
            action=action,
            reason=raw,
            raw_response=raw,
            latency_ms=latency_ms,
            provider_name="NVIDIA NIM",
            model=self._model,
        )

    async def health_check(self) -> tuple[bool, int]:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                return resp.status_code == 200, latency_ms
        except Exception:
            return False, int((time.perf_counter() - start) * 1000)

    def provider_type(self) -> str:
        return "nvidia_nim"

    @staticmethod
    def _parse(text: str) -> tuple[str, str]:
        lower = text.lower()
        if "bullish" in lower:
            return "BULLISH", "BUY"
        elif "bearish" in lower:
            return "BEARISH", "SELL"
        return "NEUTRAL", "WAIT"
