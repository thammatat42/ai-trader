"""Pydantic schemas for AI providers and analysis log."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
#  AI Provider
# ---------------------------------------------------------------------------
class AiProviderResponse(BaseModel):
    id: UUID
    name: str
    provider_type: str
    endpoint_url: str
    model: str
    max_tokens: int
    temperature: float
    config_json: dict = {}
    is_active: bool
    last_health_at: datetime | None = None
    avg_latency_ms: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AiProviderCreateRequest(BaseModel):
    name: str = Field(..., max_length=100)
    provider_type: str = Field(..., max_length=50)
    endpoint_url: str = Field(..., max_length=500)
    model: str = Field(..., max_length=200)
    api_key: str = Field(..., min_length=1)
    max_tokens: int = Field(default=100, ge=1, le=16384)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    config_json: dict = {}


class AiProviderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    endpoint_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    api_key: str | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=16384)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    config_json: dict | None = None


class AiProviderTestResponse(BaseModel):
    is_healthy: bool
    latency_ms: int
    message: str


# ---------------------------------------------------------------------------
#  AI Analysis Log
# ---------------------------------------------------------------------------
class AiAnalysisLogResponse(BaseModel):
    id: UUID
    ai_provider_id: UUID | None = None
    platform_id: UUID | None = None
    symbol: str
    bid: float | None = None
    ask: float | None = None
    ai_recommendation: str | None = None
    sentiment: str | None = None
    trade_action: str
    lot_size: float | None = None
    sl_price: float | None = None
    tp_price: float | None = None
    latency_ms: int | None = None
    correlation_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AiAnalysisRequest(BaseModel):
    """Request an AI analysis for a given symbol on a platform."""
    platform_id: UUID
    symbol: str = Field(default="XAUUSD", max_length=30)
